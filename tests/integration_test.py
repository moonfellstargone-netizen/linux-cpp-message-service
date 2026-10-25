#!/usr/bin/env python3
"""Bounded functional and fault checks for the Linux message service.

No third-party modules are required. This suite is not a throughput benchmark.
Example: python3 tests/integration_test.py --server build/message_server \
             --client build/message_client --report build/test-report.json
"""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone


CONFIG = None
IO_TIMEOUT = 2.0
MAX_BODY = 1024
CLIENT_TIMEOUT = 5.0
INPUT_REJECTED = b"Input must contain 1..1024 bytes; nothing was sent.\n"


def frame(body):
    return struct.pack("!I", len(body)) + body


def response(body):
    return b"bytes=" + str(len(body)).encode("ascii") + b"\n" + body


def receive_exact(peer, size):
    data = bytearray()
    deadline = time.monotonic() + IO_TIMEOUT
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for a complete response")
        peer.settimeout(remaining)
        chunk = peer.recv(size - len(data))
        if not chunk:
            raise EOFError("connection closed before complete response")
        data.extend(chunk)
    return bytes(data)


def receive_frame(peer):
    length = struct.unpack("!I", receive_exact(peer, 4))[0]
    if not 1 <= length <= 1056:
        raise AssertionError("invalid response body length: %d" % length)
    return receive_exact(peer, length)


def scenario(connections, request_sizes, purpose):
    def decorate(method):
        method.conditions = {
            "maximum_simultaneous_client_connections": connections,
            "request_body_bytes": request_sizes,
            "purpose": purpose,
        }
        return method
    return decorate


class RunningServer:
    """Each case owns a separate process and an ordinary temporary log file."""

    def __init__(self, executable, pipe_stderr=False):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="message-service-test-")
        self.log_path = Path(self.temp_dir.name) / "server.log"
        self.log_file = self.log_path.open("wb", buffering=0)
        self.process = None
        try:
            self.process = subprocess.Popen(
                [str(executable), "0"],
                stdin=subprocess.DEVNULL,
                stdout=self.log_file,
                stderr=subprocess.PIPE if pipe_stderr else subprocess.STDOUT,
            )
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                match = re.search(r"event=listening\s+port=(\d+)", self.read_log())
                if match:
                    self.port = int(match.group(1))
                    if not 1 <= self.port <= 65535:
                        raise RuntimeError("server logged an invalid listening port")
                    return
                if self.process.poll() is not None:
                    raise RuntimeError("server exited during startup:\n" + self.read_log())
                time.sleep(0.02)
            raise TimeoutError("no listening log within 5 seconds:\n" + self.read_log())
        except BaseException:
            self.close()
            raise

    def read_log(self):
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def connect(self):
        peer = socket.create_connection(("127.0.0.1", self.port), IO_TIMEOUT)
        peer.settimeout(IO_TIMEOUT)
        return peer

    def close(self):
        forced_kill = False
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                forced_kill = True
                self.process.kill()
                self.process.wait(timeout=3.0)
        if self.process is not None and self.process.stderr is not None:
            if not self.process.stderr.closed:
                self.process.stderr.close()
        self.last_log = self.read_log()
        self.log_file.close()
        self.temp_dir.cleanup()
        return forced_kill


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.observations = {}
        self.server = RunningServer(CONFIG.server)
        self.addCleanup(self.close_server)

    def tearDown(self):
        self.assertIsNone(self.server.process.poll(), "server exited before test cleanup")

    def close_server(self):
        forced_kill = self.server.close()
        self.observations["server_forced_kill_during_cleanup"] = forced_kill
        self.observations["server_exit_code_after_shutdown"] = self.server.process.returncode
        self.observations["server_log_tail"] = self.server.last_log[-4000:]
        self.assertFalse(forced_kill, "server did not stop within the normal shutdown deadline")
        self.assertEqual(
            self.server.process.returncode, 0,
            "server failed during shutdown:\n" + self.server.last_log[-4000:],
        )

    def exchange(self, peer, body):
        peer.sendall(frame(body))
        self.assertEqual(receive_frame(peer), response(body))

    def check_healthy(self):
        with self.server.connect() as peer:
            self.exchange(peer, b"still healthy")

    def expect_closed(self, peer):
        peer.settimeout(IO_TIMEOUT)
        try:
            self.assertEqual(peer.recv(1), b"", "invalid connection returned data")
        except (ConnectionResetError, ConnectionAbortedError):
            pass

    def run_client(self, input_bytes=None, stdin_fd=None, stdout_fd=None):
        if CONFIG.client is None:
            self.skipTest("--client was not supplied")
        arguments = {"input": input_bytes} if stdin_fd is None else {"stdin": stdin_fd}
        return subprocess.run(
            [str(CONFIG.client), "127.0.0.1", str(self.server.port)],
            stdout=subprocess.PIPE if stdout_fd is None else stdout_fd,
            stderr=subprocess.PIPE,
            timeout=CLIENT_TIMEOUT,
            check=False,
            **arguments,
        )

    def assert_client_output(self, completed, expected_requests, rejected_lines=0):
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        expected_stdout = b"".join(response(body) + b"\n" for body in expected_requests)
        self.assertEqual(completed.stdout, expected_stdout, "unexpected client response sequence")
        self.assertEqual(completed.stderr, INPUT_REJECTED * rejected_lines)

    @scenario(3, [5, 4, 5], "multiple live connections and repeated exchanges")
    def test_multiple_clients(self):
        peers = []
        try:
            for _ in range(3):
                peers.append(self.server.connect())
            for _ in range(3):
                for peer, body in zip(peers, [b"alpha", b"beta", b"gamma"]):
                    peer.sendall(frame(body))
                for peer, body in zip(peers, [b"alpha", b"beta", b"gamma"]):
                    self.assertEqual(receive_frame(peer), response(body))
        finally:
            for peer in peers:
                peer.close()

    @scenario(1, [len("你好，网络".encode("utf-8"))], "UTF-8 counts bytes, not characters")
    def test_utf8_byte_count(self):
        body = "你好，网络".encode("utf-8")
        self.assertNotEqual(len(body), len("你好，网络"))
        with self.server.connect() as peer:
            self.exchange(peer, body)

    @scenario(1, [5], "embedded NUL bytes are preserved")
    def test_embedded_nul(self):
        with self.server.connect() as peer:
            self.exchange(peer, b"a\x00b\x00c")

    @scenario(1, [1, 1024], "minimum and maximum valid request length")
    def test_valid_boundaries(self):
        with self.server.connect() as peer:
            self.exchange(peer, b"x")
            self.exchange(peer, bytes(range(256)) * 4)

    @scenario(1, [19], "header and body arrive in separate writes")
    def test_fragmented_header_and_body(self):
        body = b"fragmented-message!"
        packet = frame(body)
        with self.server.connect() as peer:
            for part in [packet[:1], packet[1:3], packet[3:4], packet[4:9]]:
                peer.sendall(part)
                peer.settimeout(0.05)
                with self.assertRaises(socket.timeout):
                    peer.recv(1)
            peer.settimeout(IO_TIMEOUT)
            peer.sendall(packet[9:])
            self.assertEqual(receive_frame(peer), response(body))

    @scenario(1, [1, 6, 1024], "several frames are coalesced in one application write")
    def test_coalesced_frames(self):
        bodies = [b"a", b"second", b"z" * MAX_BODY]
        with self.server.connect() as peer:
            peer.sendall(b"".join(frame(body) for body in bodies))
            for body in bodies:
                self.assertEqual(receive_frame(peer), response(body))

    @scenario(1, [0, 1025, 0xFFFFFFFF], "invalid lengths rejected from header alone")
    def test_invalid_length_header_only(self):
        for length in [0, MAX_BODY + 1, 0xFFFFFFFF]:
            with self.subTest(declared_body_bytes=length):
                with self.server.connect() as peer:
                    peer.sendall(struct.pack("!I", length))
                    self.expect_closed(peer)
                self.check_healthy()

    @scenario(1, [5], "truncated header/body followed by orderly EOF")
    def test_incomplete_orderly_eof(self):
        packet = frame(b"hello")
        for prefix in [packet[:2], packet[:6]]:
            with self.subTest(bytes_sent=len(prefix)):
                with self.server.connect() as peer:
                    peer.sendall(prefix)
                    peer.shutdown(socket.SHUT_WR)
                    self.expect_closed(peer)
                self.check_healthy()

    @scenario(2, [5], "truncated header/body followed by TCP reset")
    def test_incomplete_reset(self):
        packet = frame(b"hello")
        for prefix in [packet[:2], packet[:6]]:
            with self.subTest(bytes_sent=len(prefix)):
                peer = self.server.connect()
                try:
                    peer.sendall(prefix)
                    peer.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                finally:
                    peer.close()
                self.check_healthy()

    @scenario(2, [0, 6], "one protocol error leaves an existing peer usable")
    def test_error_isolation(self):
        with self.server.connect() as healthy:
            self.exchange(healthy, b"before")
            with self.server.connect() as invalid:
                invalid.sendall(struct.pack("!I", 0))
                self.expect_closed(invalid)
            self.exchange(healthy, b"after!")

    @scenario(1, [18], "complete request survives write half-close")
    def test_half_close_complete_frame(self):
        body = b"half-close request"
        with self.server.connect() as peer:
            peer.sendall(frame(body))
            peer.shutdown(socket.SHUT_WR)
            self.assertEqual(receive_frame(peer), response(body))
            self.expect_closed(peer)

    @scenario(1, [12], "50 sequential connections release process descriptors")
    def test_repeated_connections_release_fds(self):
        fd_path = Path("/proc") / str(self.server.process.pid) / "fd"
        if not fd_path.is_dir():
            self.skipTest("Linux /proc/<pid>/fd is required for this check")
        before = len(list(fd_path.iterdir()))
        for _ in range(50):
            with self.server.connect() as peer:
                self.exchange(peer, b"repeat-check")
        deadline = time.monotonic() + 3.0
        after = len(list(fd_path.iterdir()))
        while after > before and time.monotonic() < deadline:
            time.sleep(0.02)
            after = len(list(fd_path.iterdir()))
        self.observations.update(
            sequential_connections=50,
            server_fds_before=before,
            server_fds_after=after,
        )
        self.assertLessEqual(after, before, "accepted descriptors were not reclaimed")
        self.check_healthy()

    @scenario(65, [8], "64 accepted peers stay usable when the next peer is rejected")
    def test_connection_limit_isolation(self):
        peers = []
        try:
            for _ in range(64):
                peer = self.server.connect()
                peers.append(peer)
                # A reply confirms accept() completed before testing the limit.
                self.exchange(peer, b"capacity")
            with self.server.connect() as excess:
                self.expect_closed(excess)
            self.exchange(peers[0], b"capacity")
            self.observations["accepted_connections_held"] = 64
            self.observations["excess_connection_rejected"] = True
        finally:
            for peer in peers:
                peer.close()

    @scenario(2, [1024, 13], "bounded non-reading peer exercise with healthy peer")
    def test_slow_reader_does_not_block_healthy_peer(self):
        stop = threading.Event()
        started = threading.Event()
        state = {"confirmed_request_bytes_sent": 0, "outcome": "not_started"}
        slow = self.server.connect()
        slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        slow.settimeout(0.2)
        chunk = frame(b"s" * MAX_BODY) * 16
        byte_budget = 8 * 1024 * 1024

        def produce():
            started.set()
            deadline = time.monotonic() + 2.0
            try:
                while not stop.is_set() and time.monotonic() < deadline:
                    if state["confirmed_request_bytes_sent"] + len(chunk) > byte_budget:
                        state["outcome"] = "byte_budget_reached"
                        return
                    slow.sendall(chunk)
                    state["confirmed_request_bytes_sent"] += len(chunk)
                state["outcome"] = "stopped_or_time_budget_reached"
            except socket.timeout:
                state["outcome"] = "send_timeout"
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                state["outcome"] = "peer_closed"
            except OSError as error:
                if stop.is_set():
                    state["outcome"] = "closed_during_cleanup"
                else:
                    state["outcome"] = "unexpected_socket_error: " + str(error)

        writer = threading.Thread(target=produce, name="bounded-slow-peer", daemon=True)
        try:
            writer.start()
            self.assertTrue(started.wait(timeout=1.0))
            time.sleep(0.1)
            self.check_healthy()
        finally:
            stop.set()
            writer.join(timeout=1.0)
            slow.close()
            writer.join(timeout=1.0)
            self.observations.update(state)
            self.observations["request_wire_byte_budget"] = byte_budget
            self.observations["producer_time_budget_seconds"] = 2.0
            self.observations["does_not_prove_partial_send_branch_coverage"] = True
        self.assertFalse(writer.is_alive(), "bounded producer did not stop")
        self.assertFalse(state["outcome"].startswith("unexpected_socket_error"), state)

    @scenario(1, [12], "real command-line client reads stdin and prints response")
    def test_client_smoke(self):
        self.assert_client_output(self.run_client(b"client smoke\n"), [b"client smoke"])

    @scenario(1, [1024, 15], "2 MiB and 1025-byte stdin lines are rejected before valid-line recovery")
    def test_client_bounded_line_recovery(self):
        huge_length = 2 * 1024 * 1024
        valid = b"v" * MAX_BODY
        after = b"after oversized"
        input_bytes = b"x" * huge_length + b"\n" + valid + b"\n" + b"y" * 1025 + b"\n" + after + b"\n"
        self.observations.update(
            stdin_line_bytes=[huge_length, len(valid), 1025, len(after)],
            expected_sent_request_body_bytes=[len(valid), len(after)],
            expected_local_rejections=2,
            client_process_timeout_seconds=CLIENT_TIMEOUT,
            memory_usage_not_measured=True,
        )
        self.assert_client_output(self.run_client(input_bytes), [valid, after], rejected_lines=2)

    @scenario(1, [1024, 5], "UTF-8 byte boundary, empty-line recovery, and /quit ignores later stdin")
    def test_client_utf8_empty_and_quit(self):
        prefix = "你".encode("utf-8") * 341
        valid = prefix + b"x"
        invalid = prefix + b"xy"
        self.assertEqual(len(valid), 1024)
        self.assertEqual(len(invalid), 1025)
        input_bytes = b"\n" + valid + b"\n" + invalid + b"\nready\n/quit\nnot sent\n"
        self.observations.update(
            stdin_line_bytes=[0, len(valid), len(invalid), 5, 5, 8],
            expected_sent_request_body_bytes=[len(valid), 5],
            expected_local_rejections=2,
            client_process_timeout_seconds=CLIENT_TIMEOUT,
        )
        self.assert_client_output(self.run_client(input_bytes), [valid, b"ready"], rejected_lines=2)

    @scenario(1, [8], "EOF without newline sends one valid tail but rejects an oversized tail")
    def test_client_eof_tail_lines(self):
        self.observations.update(
            separate_client_stdin_bytes=[8, 1025],
            trailing_newline=False,
            expected_sent_request_body_bytes=[8],
            expected_local_rejections=1,
            client_process_timeout_seconds=CLIENT_TIMEOUT,
        )
        with self.subTest(tail="valid"):
            self.assert_client_output(self.run_client(b"tail EOF"), [b"tail EOF"])
        with self.subTest(tail="oversized"):
            self.assert_client_output(self.run_client(b"x" * 1025), [], rejected_lines=1)

    @scenario(1, [], "Linux directory stdin descriptor produces a read error and nonzero exit")
    def test_client_stdin_read_error(self):
        if platform.system() != "Linux":
            self.skipTest("directory-descriptor stdin error check requires Linux")
        if CONFIG.client is None:
            self.skipTest("--client was not supplied")
        stdin_fd = os.open(self.server.temp_dir.name, os.O_RDONLY | os.O_DIRECTORY)
        try:
            completed = self.run_client(stdin_fd=stdin_fd)
        finally:
            os.close(stdin_fd)
        self.observations.update(
            stdin_source="read-only directory descriptor (read returns EISDIR)",
            expected_sent_request_body_bytes=[],
            client_process_timeout_seconds=CLIENT_TIMEOUT,
            client_exit_code=completed.returncode,
        )
        self.assertNotEqual(completed.returncode, 0, "stdin read error was reported as successful EOF")
        self.assertEqual(completed.stdout, b"")
        self.assertEqual(completed.stderr, b"message_client: stdin read failed\n")

    @scenario(1, [12, 13], "client reply/help stdout failures return nonzero while server remains healthy")
    def test_client_stdout_write_error(self):
        if platform.system() != "Linux":
            self.skipTest("/dev/full stdout error check requires Linux")
        if CONFIG.client is None:
            self.skipTest("--client was not supplied")
        body = b"stdout error"
        self.observations.update(
            stdout_target="/dev/full (writes fail with ENOSPC)",
            client_process_timeout_seconds=CLIENT_TIMEOUT,
            healthy_probe_body_bytes=len(b"still healthy"),
            stdout_error_subcases=[],
        )
        stdout_fd = os.open("/dev/full", os.O_WRONLY)
        try:
            for mode in ["reply", "help"]:
                with self.subTest(mode=mode):
                    if mode == "reply":
                        completed = self.run_client(body + b"\n", stdout_fd=stdout_fd)
                    else:
                        completed = subprocess.run(
                            [str(CONFIG.client), "--help"],
                            stdin=subprocess.DEVNULL,
                            stdout=stdout_fd,
                            stderr=subprocess.PIPE,
                            timeout=CLIENT_TIMEOUT,
                            check=False,
                        )
                    self.observations["stdout_error_subcases"].append({
                        "mode": mode,
                        "request_body_bytes": len(body) if mode == "reply" else 0,
                        "stdin_bytes": len(body) + 1 if mode == "reply" else 0,
                        "connects_to_server": mode == "reply",
                        "client_exit_code": completed.returncode,
                    })
                    self.assertIsNone(self.server.process.poll(), "client output error stopped the server")
                    if mode == "reply":
                        self.check_healthy()
                    self.assertNotEqual(completed.returncode, 0, "stdout write failure returned success")
                    self.assertEqual(completed.stderr, b"message_client: stdout write failed\n")
        finally:
            os.close(stdout_fd)

    @scenario(1, [20], "closed stderr pipe does not terminate the server during connection logging")
    def test_closed_stderr_pipe_isolation(self):
        isolated = RunningServer(CONFIG.server, pipe_stderr=True)

        def close_isolated_server():
            forced_kill = isolated.close()
            self.observations["closed_stderr_server"] = {
                "forced_kill_during_cleanup": forced_kill,
                "exit_code_after_shutdown": isolated.process.returncode,
                "stdout_log_tail": isolated.last_log[-4000:],
            }
            self.assertFalse(forced_kill, "closed-stderr server did not stop normally")
            self.assertEqual(isolated.process.returncode, 0, "closed-stderr server shutdown failed")

        self.addCleanup(close_isolated_server)
        # Never read this pipe: closing its reader makes the next stderr write
        # exercise EPIPE/SIGPIPE without risking a blocking read in the suite.
        isolated.process.stderr.close()
        self.observations.update(stderr_pipe_reader_closed=True, server_processes_in_case=2)
        with isolated.connect() as peer:
            self.exchange(peer, b"after stderr closure")
        self.assertIsNone(isolated.process.poll(), "closed stderr pipe terminated the server")


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def startTest(self, test):
        self.case_started = time.monotonic()
        self.record = {
            "case": test.id().rsplit(".", 1)[-1],
            "status": "passed",
            "conditions": getattr(getattr(test, test._testMethodName), "conditions", {}),
        }
        super().startTest(test)

    def addFailure(self, test, err):
        self.record.update(status="failed", detail=self._exc_info_to_string(err, test))
        super().addFailure(test, err)

    def addError(self, test, err):
        self.record.update(status="error", detail=self._exc_info_to_string(err, test))
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.record.update(status="skipped", detail=reason)
        super().addSkip(test, reason)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.record.update(status="failed", detail=self._exc_info_to_string(err, test))
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        self.record["elapsed_seconds"] = time.monotonic() - self.case_started
        self.record["observations"] = getattr(test, "observations", {})
        self.records.append(self.record)
        super().stopTest(test)


def environment():
    cpu_model = platform.processor() or "unknown"
    cpu_info = Path("/proc/cpuinfo")
    if cpu_info.is_file():
        for line in cpu_info.read_text(errors="replace").splitlines():
            if line.startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    memory_bytes = None
    try:
        memory_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        pass
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "kernel_release": platform.release(),
        "machine": platform.machine(),
        "cpu_model": cpu_model,
        "logical_cpu_count": os.cpu_count(),
        "physical_memory_bytes": memory_bytes,
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "server_executable": str(CONFIG.server),
        "client_executable": str(CONFIG.client) if CONFIG.client else None,
        "network": "IPv4 loopback 127.0.0.1; ephemeral server port per case",
        "per_response_timeout_seconds": IO_TIMEOUT,
    }


def main():
    global CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, type=Path)
    parser.add_argument("--client", type=Path)
    parser.add_argument("--report", type=Path, help="write measured functional test results as JSON")
    CONFIG = parser.parse_args()
    CONFIG.server = CONFIG.server.resolve()
    if CONFIG.client is not None:
        CONFIG.client = CONFIG.client.resolve()
    for executable in [CONFIG.server, CONFIG.client]:
        if executable is not None and not executable.is_file():
            parser.error("executable does not exist: " + str(executable))
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IntegrationTests)
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
    report = {
        "report_type": "functional_and_fault_validation_not_a_performance_benchmark",
        "started_at_utc": started_at,
        "elapsed_seconds": time.monotonic() - started,
        "environment": environment(),
        "summary": {
            "cases_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "successful": result.wasSuccessful(),
        },
        "cases": result.records,
        "limits": [
            "Loopback functional checks do not establish production capacity or reliable delivery.",
            "Write fragmentation does not guarantee matching TCP segment boundaries.",
            "The slow-peer case does not prove the C++ partial-send branch executed.",
            "Timeouts bound functional checks; elapsed times are not throughput or latency benchmarks.",
        ],
    }
    if CONFIG.report is not None:
        CONFIG.report.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Functional test report:", CONFIG.report.resolve())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
