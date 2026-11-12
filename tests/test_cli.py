import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, "-I", "-B", str(ROOT / "classic_histogram_audit.py")]


def bucket(bound, count, timestamp=1700000000, **labels):
    return {"metric": {"__name__": "request_seconds_bucket", "le": bound, **labels},
            "value": [timestamp, count]}


def total(count, timestamp=1700000000, **labels):
    return {"metric": {"__name__": "request_seconds_count", **labels}, "value": [timestamp, count]}


def envelope(rows, result_type="vector"):
    return {"status": "success", "data": {"resultType": result_type, "result": rows}}


class CliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.fixture = Path(directory.name) / "PRIVATE_NAME.json"

    def result(self, expected, metric="request_seconds", prefix=()):
        completed = subprocess.run([*CLI, *prefix, str(self.fixture), metric],
                                   capture_output=True, timeout=10)
        self.assertEqual(completed.returncode, expected, completed.stderr)
        self.assertEqual(completed.stderr, b"")
        self.assertNotIn(b"PRIVATE", completed.stdout)
        return json.loads(completed.stdout)

    def audit(self, rows, code=0):
        self.fixture.write_text(json.dumps(envelope(rows)), encoding="utf-8")
        return self.result(code)

    def invalid(self, raw, code, row=None):
        self.fixture.write_bytes(raw)
        self.assertEqual(self.result(2), {"status": "invalid", "code": code, "row": row})

    def test_reverse_order_and_decimal_equivalence(self):
        result = self.audit([bucket("+Inf", "8.00"), total("8e0"), bucket("10", "8"),
                             bucket("1", "5"), bucket("-0.5", "0")])
        self.assertEqual(result, {"status": "clean", "groups": 1, "samples": 5, "findings": []})

    def test_uses_exact_label_set_and_ignores_unrelated_rows(self):
        unrelated = {"metric": {"__name__": "other_count"}, "value": [1, "NaN"]}
        result = self.audit([bucket("+Inf", "1", region="one", owner="私人"),
                             unrelated, total("2", region="two", owner="私人"),
                             total("1", owner="私人", region="one"),
                             bucket("+Inf", "2", owner="私人", region="two")])
        self.assertEqual((result["groups"], result["samples"]), (2, 4))

    def test_numeric_order_and_count_mismatch(self):
        result = self.audit([bucket("10", "4"), bucket("+Inf", "3"), bucket("2", "5"), total("9")], 1)
        self.assertEqual(result["findings"], [{"code": "decreasing_bucket", "rows": [3, 1]},
                                               {"code": "decreasing_bucket", "rows": [1, 2]},
                                               {"code": "count_mismatch", "rows": [2, 4]}])

    def test_exact_count_comparison_above_binary_float_precision(self):
        result = self.audit([bucket("+Inf", "9007199254740992"), total("9007199254740993")], 1)
        self.assertEqual(result["findings"], [{"code": "count_mismatch", "rows": [1, 2]}])

    def test_reports_missing_components_per_label_group(self):
        result = self.audit([bucket("10", "5", instance="PRIVATE_A"),
                             total("9", instance="PRIVATE_B")], 1)
        self.assertEqual(result["findings"], [{"code": "missing_infinity", "rows": [1]},
                                               {"code": "missing_count", "rows": [1]},
                                               {"code": "missing_infinity", "rows": [2]}])

    def test_duplicate_numeric_bounds_and_totals_suppress_arithmetic(self):
        result = self.audit([bucket("1", "10"), bucket("1.0", "1"), bucket("+Inf", "2"),
                             total("9"), total("10")], 1)
        self.assertEqual(result["findings"], [{"code": "duplicate_bucket", "rows": [1, 2]},
                                               {"code": "duplicate_count", "rows": [4, 5]}])

    def test_mixed_timestamps_suppress_arithmetic(self):
        result = self.audit([bucket("0.5", "9", 1.75), bucket("+Inf", "2", 1.75),
                             total("10", 1.751)], 1)
        self.assertEqual(result["findings"], [{"code": "timestamp_mismatch", "rows": [1, 3]}])

    def test_timestamps_from_different_groups_may_differ(self):
        self.audit([bucket("+Inf", "1", 2.75, route="a"), total("1", 2.75, route="a"),
                    bucket("+Inf", "2", 3.5, route="b"), total("2", 3.5, route="b")])

    def test_empty_or_unrelated_vector_is_invalid(self):
        for rows in ([], [{"metric": {"__name__": "other_count"}, "value": [1, "1"]}]):
            with self.subTest(rows=rows):
                self.invalid(json.dumps(envelope(rows)).encode(), "no_matching_samples")

    def test_bad_bucket_and_count_values(self):
        for sample, expected in ((bucket("Infinity", "2"), "invalid_bucket_bound"),
                                 (bucket("1e10001", "2"), "invalid_bucket_bound"),
                                 (bucket("PRIVATE", "2"), "invalid_bucket_bound"),
                                 (bucket("1", "NaN"), "invalid_count"),
                                 (bucket("1", "-0.1"), "invalid_count"),
                                 (total("5", le="1"), "invalid_count_labels"),
                                 (total(5), "invalid_float_sample"),
                                 (total("5", True), "invalid_float_sample"),
                                 ({"metric": {"__name__": "request_seconds_count"},
                                   "histogram": [1, {}]}, "invalid_float_sample")):
            with self.subTest(expected=expected, sample=sample):
                self.invalid(json.dumps(envelope([sample])).encode(), expected, 1)

    def test_strict_json_and_vector_shape(self):
        for raw, expected in ((b"\xff", "invalid_json"),
                              (b'{"status":"success","status":"error"}', "invalid_json"),
                              (b'{"value":NaN}', "invalid_json"),
                              (b"[" * 5000 + b"]" * 5000, "invalid_json"),
                              (b'{"status":"error"}', "expected_success_response"),
                              (json.dumps(envelope([], "matrix")).encode(), "expected_instant_vector"),
                              (json.dumps(envelope({})).encode(), "expected_vector_rows")):
            with self.subTest(expected=expected):
                self.invalid(raw, expected)

    def test_malformed_labels_do_not_echo(self):
        for labels in (None, {"value": 3}, {"value": "\ud800"}):
            with self.subTest(labels=labels):
                self.invalid(json.dumps(envelope([{"metric": labels}])).encode(), "invalid_labels", 1)

    def test_file_limit_and_row_limit(self):
        self.invalid(b" " * (2 * 1024 * 1024 + 1), "input_too_large")
        self.invalid(json.dumps(envelope([{"metric": {}}] * 10001)).encode(), "too_many_rows")

    def test_unreadable_and_non_regular_input(self):
        self.assertEqual(self.result(2)["code"], "input_unreadable")
        self.fixture.mkdir()
        self.assertEqual(self.result(2)["code"], "input_not_regular")

    @unittest.skipUnless(os.name == "nt", "Windows file namespace")
    def test_explicit_windows_namespace_and_stream_paths_are_rejected(self):
        for name in (r"\\localhost\PRIVATE_SHARE\PRIVATE_NAME.json",
                     r"\\?\C:\PRIVATE_NAME.json", "NUL", str(self.fixture) + ":PRIVATE_STREAM"):
            with self.subTest(name=name):
                completed = subprocess.run([*CLI, name, "request_seconds"], capture_output=True, timeout=10)
                self.assertEqual((completed.returncode, json.loads(completed.stdout), completed.stderr),
                                 (2, {"status": "invalid", "code": "input_not_regular", "row": None}, b""))

    def test_usage_does_not_echo_unexpected_arguments(self):
        completed = subprocess.run([*CLI, "--PRIVATE"], capture_output=True, timeout=10)
        self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                         (2, b'{"status":"invalid","code":"usage","row":null}\n', b""))
        self.assertEqual(self.result(2, "PRIVATE.invalid")["code"], "invalid_metric_base")

    def test_closed_output_pipe_for_help_and_invalid_report(self):
        for args in (["--help"], ["--PRIVATE"], ["examples/clean.json", "request_seconds"]):
            with self.subTest(args=args):
                read_end, write_end = os.pipe()
                os.close(read_end)
                try:
                    completed = subprocess.run([*CLI, *args], cwd=ROOT, stdout=write_end,
                                               stderr=subprocess.PIPE, timeout=10)
                finally:
                    os.close(write_end)
                self.assertEqual((completed.returncode, completed.stderr), (2, b""))


if __name__ == "__main__":
    unittest.main()
