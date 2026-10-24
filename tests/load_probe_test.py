#!/usr/bin/env python3
"""Regression checks for load_probe CLI validation and report consistency.

The successful case makes a short real loopback run. These tests do not set a
throughput target or independently implement the probe's timing algorithm.
"""

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CONFIG = None
PROBE_PATH = Path(__file__).resolve().with_name("load_probe.py")


class LoadProbeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="load-probe-regression-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def invoke_probe(self, overrides=None, server=None, report_name="report.json", timeout=20):
        arguments = {"connections": "2", "message-bytes": "64", "duration": "0.2"}
        arguments.update(overrides or {})
        report_path = self.directory / report_name
        command = [
            sys.executable,
            str(PROBE_PATH),
            "--server",
            str(CONFIG.server if server is None else server),
            "--report",
            str(report_path),
        ]
        # The = form makes values such as -inf reach the duration validator.
        command.extend("--%s=%s" % (name, value) for name, value in arguments.items())
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        return completed, report_path

    def check_integer(self, value, minimum=0):
        self.assertIs(type(value), int)
        self.assertGreaterEqual(value, minimum)

    def check_finite_number(self, value, strictly_positive=False):
        self.assertIn(type(value), (int, float))
        self.assertTrue(math.isfinite(value))
        if strictly_positive:
            self.assertGreater(value, 0)
        else:
            self.assertGreaterEqual(value, 0)

    def test_short_real_run_report_consistency(self):
        completed, report_path = self.invoke_probe()
        self.assertEqual(
            completed.returncode,
            0,
            "probe failed:\nstdout:\n%s\nstderr:\n%s" % (completed.stdout, completed.stderr),
        )
        self.assertTrue(report_path.is_file(), "successful probe did not write its report")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIs(report["successful"], True)

        conditions = report["conditions"]
        self.assertEqual(conditions["connections"], 2)
        self.assertEqual(conditions["message_body_bytes"], 64)
        self.assertEqual(conditions["requested_duration_seconds"], 0.2)
        warmup_count = conditions["warmup_requests_per_connection"]
        self.check_integer(warmup_count, minimum=1)

        workers = report["workers"]
        self.assertEqual(len(workers), 2)
        for worker in workers:
            self.assertIsNone(worker["error"], worker)
            self.check_integer(worker["completed_requests"])
            self.assertEqual(worker["warmup_completed"], warmup_count)

        summary = report["summary"]
        self.assertIsInstance(summary, dict)
        count = summary["completed_requests"]
        self.check_integer(count, minimum=1)
        self.assertEqual(count, sum(worker["completed_requests"] for worker in workers))
        self.check_finite_number(summary["elapsed_seconds"], strictly_positive=True)
        self.check_finite_number(summary["completed_requests_per_second"], strictly_positive=True)
        for field in ["rtt_mean_ms", "rtt_min_ms", "rtt_max_ms"]:
            self.check_finite_number(summary[field])
        self.assertLessEqual(summary["rtt_min_ms"], summary["rtt_mean_ms"])
        self.assertLessEqual(summary["rtt_mean_ms"], summary["rtt_max_ms"])

        # Only successfully completed measured exchanges are counted; warmup
        # and transport/network overhead do not belong in these byte totals.
        request_frame_bytes = 4 + 64
        response_frame_bytes = 4 + len(b"bytes=64\n") + 64
        self.assertEqual(summary["request_application_frame_bytes"], count * request_frame_bytes)
        self.assertEqual(summary["response_application_frame_bytes"], count * response_frame_bytes)

        server = report["server"]
        self.assertEqual(server["exit_code"], 0)
        self.assertIs(server["forced_kill"], False)
        self.assertIsInstance(report["environment"], dict)
        self.assertTrue(report["environment"], "machine environment must be recorded")

    def test_invalid_cli_ranges_are_rejected(self):
        invalid_arguments = [
            ("connections", "0"),
            ("connections", "17"),
            ("message-bytes", "0"),
            ("message-bytes", "1025"),
            ("duration", "nan"),
            ("duration", "inf"),
            ("duration", "-inf"),
            ("duration", "0"),
            ("duration", "0.09"),
            ("duration", "30.1"),
        ]
        for index, (argument, value) in enumerate(invalid_arguments):
            with self.subTest(argument=argument, value=value):
                completed, report_path = self.invoke_probe(
                    {argument: value}, report_name="invalid-%d.json" % index, timeout=5
                )
                self.assertNotEqual(completed.returncode, 0, "invalid CLI input was accepted")
                self.assertTrue(completed.stderr.strip(), "rejected input needs an error diagnostic")
                self.assertFalse(report_path.exists(), "invalid arguments must not produce a measurement report")

    def test_missing_server_is_an_explicit_failure(self):
        missing = self.directory / "missing-message-server"
        self.assertFalse(missing.exists())
        completed, report_path = self.invoke_probe(server=missing, timeout=5)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(completed.stderr.strip(), "missing server needs an error diagnostic")
        self.assertIn(missing.name, completed.stderr)
        # Argument validation may reject the path before a JSON report exists.
        # If one is emitted, it must not advertise a successful measurement.
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIs(report["successful"], False)
            self.assertIsNone(report["summary"])

    def test_startup_failure_has_no_successful_measurement(self):
        # This existing executable exits immediately without a listening socket.
        # It exercises runtime failure, rather than only argument validation.
        false_program = Path("/bin/false")
        self.assertTrue(false_program.is_file(), "Ubuntu /bin/false is required")
        completed, report_path = self.invoke_probe(server=false_program, timeout=10)
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(report_path.is_file(), "runtime failure should leave a diagnostic report")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIs(report["successful"], False)
        self.assertIsNone(report["summary"])
        self.assertIs(report["server"]["startup_completed"], False)
        self.assertTrue(report["errors"], "startup failure needs an explicit diagnostic")


def main():
    global CONFIG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, type=Path)
    CONFIG = parser.parse_args()
    CONFIG.server = CONFIG.server.resolve()
    if not CONFIG.server.is_file():
        parser.error("server executable does not exist: " + str(CONFIG.server))
    if not PROBE_PATH.is_file():
        parser.error("load probe does not exist: " + str(PROBE_PATH))
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LoadProbeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
