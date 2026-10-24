#!/usr/bin/env python3
"""Bounded loopback observation, not a production-capacity benchmark.

Example: python3 tests/load_probe.py --server build/message_server \
             --connections 4 --message-bytes 128 --duration 3 --report build/probe.json
The JSON report is required. Timeouts bound the driver, not the server protocol.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import threading
import time

from integration_test import IO_TIMEOUT, RunningServer, frame, receive_frame, response


WARMUP_REQUESTS = 10
STARTUP_TIMEOUT = 10.0
CLEANUP_TIMEOUT = 7.0


def bounded_number(kind, minimum, maximum):
    def parse(text):
        try:
            value = kind(text)
        except ValueError:
            raise argparse.ArgumentTypeError("expected a number") from None
        if not minimum <= value <= maximum or not math.isfinite(value):
            raise argparse.ArgumentTypeError("expected %s..%s" % (minimum, maximum))
        return value
    return parse


def metadata(binary):
    source = {}
    root = Path(__file__).resolve().parent.parent
    try:
        def git(*arguments):
            return subprocess.run(["git", "-C", str(root), *arguments], check=True,
                                  capture_output=True, text=True, timeout=2).stdout.strip()
        source = {"git_sha": git("rev-parse", "HEAD"),
                  "git_dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        pass
    digest = hashlib.sha256()
    with binary.open("rb") as executable:
        for chunk in iter(lambda: executable.read(65536), b""):
            digest.update(chunk)
    build = {}
    for directory in list(binary.parents)[:3]:
        cache = directory / "CMakeCache.txt"
        if cache.is_file():
            entries = {}
            for line in cache.read_text(errors="replace").splitlines():
                if not line.startswith(("#", "//")) and ":" in line and "=" in line:
                    key, value = line.split("=", 1)
                    entries[key.split(":", 1)[0]] = value
            build = {"cache_path": str(cache)}
            for output, key in [("build_type", "CMAKE_BUILD_TYPE"),
                                ("cxx_compiler", "CMAKE_CXX_COMPILER"),
                                ("cxx_flags", "CMAKE_CXX_FLAGS"),
                                ("sanitizers", "MSG_ENABLE_SANITIZERS")]:
                if key in entries:
                    build[output] = entries[key]
            mode_key = "CMAKE_CXX_FLAGS_" + entries.get("CMAKE_BUILD_TYPE", "").upper()
            if mode_key in entries:
                build["build_type_cxx_flags"] = entries[mode_key]
            break
    cpu = platform.processor() or None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    memory = None
    try:
        memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        pass
    return {"source": source, "binary": {"path": str(binary), "sha256": digest.hexdigest()},
            "build": build, "environment": {"platform": platform.platform(),
                "cpu_model": cpu, "logical_cpu_count": os.cpu_count(),
                "physical_memory_bytes": memory, "python_version": platform.python_version(),
                "python_executable": sys.executable}}


def observe(arguments):
    workers = [{"worker_id": index, "completed_requests": 0, "warmup_completed": 0,
                "rtt_total_ns": 0, "rtt_min_ns": None, "rtt_max_ns": None,
                "last_completion_ns": None, "error": None}
               for index in range(arguments.connections)]
    report = {"report_type": "bounded_loopback_request_reply_observation",
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "successful": False, "conditions": {
                  "connections": arguments.connections,
                  "message_body_bytes": arguments.message_bytes,
                  "warmup_requests_per_connection": WARMUP_REQUESTS,
                  "requested_duration_seconds": arguments.duration,
                  "in_flight_requests_per_connection": 1,
                  "network": "IPv4 loopback 127.0.0.1",
                  "io_timeout_seconds": IO_TIMEOUT,
                  "io_timeout_scope": "per send, response header, and response body"},
              "summary": None, "workers": workers, "errors": [],
              "server": {"startup_completed": False, "exit_code": None,
                         "forced_kill": None, "log_tail": ""},
              "limits": [
                  "Local driver threads, validation and scheduling affect the observations.",
                  "These results do not establish production traffic or maximum capacity.",
                  "Warmup is excluded; elapsed time includes the last completed in-flight request.",
                  "Application frame bytes include headers, not TCP/IP overhead; no percentiles."]}
    stop = threading.Event()
    rendezvous = threading.Event()
    clock = {}
    peers = [None] * arguments.connections
    peers_lock = threading.Lock()
    threads = []
    server = None

    def begin_window():
        clock["start_ns"] = time.monotonic_ns()
        clock["deadline_ns"] = clock["start_ns"] + int(arguments.duration * 1_000_000_000)
        rendezvous.set()

    barrier = threading.Barrier(arguments.connections, action=begin_window)

    def worker(index):
        record = workers[index]
        body = bytes([ord("a") + index]) * arguments.message_bytes
        packet, expected = frame(body), response(body)
        try:
            with server.connect() as peer:
                with peers_lock:
                    peers[index] = peer
                for _ in range(WARMUP_REQUESTS):
                    if stop.is_set():
                        return
                    peer.settimeout(IO_TIMEOUT)
                    peer.sendall(packet)
                    if receive_frame(peer) != expected:
                        raise AssertionError("warmup response did not match request")
                    record["warmup_completed"] += 1
                barrier.wait(timeout=STARTUP_TIMEOUT)
                while not stop.is_set() and time.monotonic_ns() < clock["deadline_ns"]:
                    started = time.monotonic_ns()
                    peer.settimeout(IO_TIMEOUT)
                    peer.sendall(packet)
                    if receive_frame(peer) != expected:
                        raise AssertionError("response did not match request")
                    completed = time.monotonic_ns()
                    rtt = completed - started
                    record["completed_requests"] += 1
                    record["rtt_total_ns"] += rtt
                    record["rtt_min_ns"] = min(record["rtt_min_ns"] or rtt, rtt)
                    record["rtt_max_ns"] = max(record["rtt_max_ns"] or rtt, rtt)
                    record["last_completion_ns"] = completed
        except Exception as error:
            record["error"] = type(error).__name__ + ": " + str(error)
            stop.set()
            barrier.abort()
            rendezvous.set()
        finally:
            with peers_lock:
                peers[index] = None

    def interrupt_peers():
        with peers_lock:
            for peer in peers:
                if peer is not None:
                    try:
                        peer.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

    try:
        report.update(metadata(arguments.server))
        server = RunningServer(arguments.server)
        report["server"]["startup_completed"] = True
        for index in range(arguments.connections):
            thread = threading.Thread(target=worker, args=(index,), daemon=True)
            thread.start()
            threads.append(thread)
        if not rendezvous.wait(timeout=STARTUP_TIMEOUT):
            raise TimeoutError("workers did not complete warmup within startup budget")
        if stop.is_set():
            interrupt_peers()
        deadline = clock.get("deadline_ns", time.monotonic_ns()) / 1e9 + CLEANUP_TIMEOUT
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            raise TimeoutError("worker exceeded measurement and cleanup budget")
        if server.process.poll() is not None:
            raise RuntimeError("server exited before normal cleanup")
    except Exception as error:
        report["errors"].append(type(error).__name__ + ": " + str(error))
    finally:
        stop.set()
        barrier.abort()
        interrupt_peers()
        deadline = time.monotonic() + IO_TIMEOUT + 1
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            report["errors"].append("worker did not stop during bounded cleanup")
        if server is not None:
            try:
                forced = server.close()
                report["server"].update(exit_code=server.process.returncode,
                                         forced_kill=forced, log_tail=server.last_log[-4000:])
            except Exception as error:
                report["errors"].append("server cleanup failed: " + str(error))
    count = sum(record["completed_requests"] for record in workers)
    report["successful"] = (not report["errors"] and
                            all(record["completed_requests"] > 0 for record in workers) and
                            all(record["error"] is None for record in workers) and
                            report["server"]["exit_code"] == 0 and
                            report["server"]["forced_kill"] is False)
    if report["successful"]:
        elapsed = (max(record["last_completion_ns"] or clock["start_ns"]
                       for record in workers) - clock["start_ns"]) / 1e9
        report["summary"] = {
            "completed_requests": count, "elapsed_seconds": elapsed,
            "completed_requests_per_second": count / elapsed,
            "rtt_mean_ms": sum(record["rtt_total_ns"] for record in workers) / count / 1e6,
            "rtt_min_ms": min(record["rtt_min_ns"] for record in workers
                              if record["rtt_min_ns"] is not None) / 1e6,
            "rtt_max_ms": max(record["rtt_max_ns"] or 0 for record in workers) / 1e6,
            "request_application_frame_bytes": count * (4 + arguments.message_bytes),
            "response_application_frame_bytes": count * len(frame(response(b"x" * arguments.message_bytes)))}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, type=Path)
    parser.add_argument("--connections", default=4, type=bounded_number(int, 1, 16))
    parser.add_argument("--message-bytes", default=128, type=bounded_number(int, 1, 1024))
    parser.add_argument("--duration", default=3.0, type=bounded_number(float, 0.1, 30))
    parser.add_argument("--report", required=True, type=Path, help="required JSON output path")
    arguments = parser.parse_args()
    arguments.server = arguments.server.resolve()
    if not arguments.server.is_file():
        parser.error("server executable does not exist: " + str(arguments.server))
    if arguments.report.resolve() == arguments.server:
        parser.error("report must not overwrite the server executable")
    report = observe(arguments)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Loopback observation report:", arguments.report.resolve())
    return 0 if report["successful"] else 1


if __name__ == "__main__":
    sys.exit(main())
