#!/usr/bin/env python3
"""Audit classic histogram counts in one saved Prometheus instant vector."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import sys


MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10_000
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
METRIC = re.compile(r"[A-Za-z_:][A-Za-z0-9_:]{0,199}")
INFINITY = Decimal("Infinity")


class InvalidInput(Exception):
    def __init__(self, code, row=None):
        self.code = code
        self.row = row


@dataclass(frozen=True)
class Sample:
    row: int
    timestamp: Decimal
    count: Decimal


@dataclass
class Histogram:
    samples: list[Sample] = field(default_factory=list)
    buckets: dict[Decimal, Sample] = field(default_factory=dict)
    total: Sample | None = None
    duplicates: list[dict] = field(default_factory=list)

    def add(self, sample, bound):
        self.samples.append(sample)
        existing = self.total if bound is None else self.buckets.get(bound)
        if existing is not None:
            code = "duplicate_count" if bound is None else "duplicate_bucket"
            self.duplicates.append(finding(code, existing, sample))
        elif bound is None:
            self.total = sample
        else:
            self.buckets[bound] = sample

    def findings(self):
        results = self.duplicates.copy()
        first = self.samples[0]
        infinity = self.buckets.get(INFINITY)
        if infinity is None:
            results.append(finding("missing_infinity", first))
        if self.total is None:
            results.append(finding("missing_count", first))
        other_time = next((sample for sample in self.samples if sample.timestamp != first.timestamp), None)
        if other_time is not None:
            results.append(finding("timestamp_mismatch", first, other_time))
        if self.duplicates or other_time is not None:
            return results
        ordered = [sample for _, sample in sorted(self.buckets.items())]
        for previous, current in zip(ordered, ordered[1:]):
            if current.count < previous.count:
                results.append(finding("decreasing_bucket", previous, current))
        if infinity is not None and self.total is not None and infinity.count != self.total.count:
            results.append(finding("count_mismatch", infinity, self.total))
        return results


def finding(code, *samples):
    return {"code": code, "rows": [sample.row for sample in samples]}


def decimal_number(text):
    if len(text) > 64 or DECIMAL.fullmatch(text) is None:
        raise ValueError("unsupported decimal")
    value = Decimal(text)
    if abs(value.adjusted()) > 10_000 or abs(value.as_tuple().exponent) > 10_000:
        raise ValueError("unsupported decimal exponent")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def read_vector(filename):
    if os.name == "nt":
        windows_path = PureWindowsPath(filename)
        if windows_path.drive.startswith("\\\\") or filename.replace("\\", "/").startswith("//"):
            raise InvalidInput("input_not_regular")
        is_reserved = getattr(os.path, "isreserved", None)
        for part in windows_path.parts[1 if windows_path.anchor else 0:]:
            reserved = is_reserved(part) if is_reserved else PureWindowsPath(part).is_reserved()
            if ":" in part or reserved:
                raise InvalidInput("input_not_regular")
    path = Path(filename)
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise InvalidInput("input_not_regular")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise InvalidInput("input_not_regular")
            raw = stream.read(MAX_BYTES + 1)
    except (OSError, ValueError):
        raise InvalidInput("input_unreadable") from None
    if len(raw) > MAX_BYTES:
        raise InvalidInput("input_too_large")
    try:
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                              parse_int=decimal_number, parse_float=decimal_number,
                              parse_constant=decimal_number)
    except (ValueError, InvalidOperation, RecursionError):
        raise InvalidInput("invalid_json") from None
    if not isinstance(envelope, dict) or envelope.get("status") != "success":
        raise InvalidInput("expected_success_response")
    data = envelope.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        raise InvalidInput("expected_instant_vector")
    vector = data.get("result")
    if not isinstance(vector, list):
        raise InvalidInput("expected_vector_rows")
    if len(vector) > MAX_ROWS:
        raise InvalidInput("too_many_rows")
    return vector


def audit(vector, metric):
    groups = {}
    matching = 0
    for ordinal, item in enumerate(vector, 1):
        labels = item.get("metric") if isinstance(item, dict) else None
        if not isinstance(labels, dict) or any(not isinstance(value, str) for value in labels.values()):
            raise InvalidInput("invalid_labels", ordinal)
        try:
            for key, value in labels.items():
                key.encode("utf-8")
                value.encode("utf-8")
        except UnicodeEncodeError:
            raise InvalidInput("invalid_labels", ordinal) from None
        name = labels.get("__name__")
        if name not in {metric + "_bucket", metric + "_count"}:
            continue
        value = item.get("value")
        if ("histogram" in item or not isinstance(value, list) or len(value) != 2
                or not isinstance(value[0], Decimal) or not isinstance(value[1], str)):
            raise InvalidInput("invalid_float_sample", ordinal)
        try:
            count = decimal_number(value[1])
        except (ValueError, InvalidOperation):
            raise InvalidInput("invalid_count", ordinal) from None
        if count < 0:
            raise InvalidInput("invalid_count", ordinal)
        bound = None
        if name.endswith("_bucket"):
            text = labels.get("le")
            if text is None:
                raise InvalidInput("invalid_bucket_bound", ordinal)
            try:
                bound = INFINITY if text == "+Inf" else decimal_number(text)
            except (ValueError, InvalidOperation):
                raise InvalidInput("invalid_bucket_bound", ordinal) from None
        elif "le" in labels:
            raise InvalidInput("invalid_count_labels", ordinal)
        identity = tuple(sorted((key, value) for key, value in labels.items() if key not in {"__name__", "le"}))
        if identity not in groups:
            groups[identity] = Histogram()
        groups[identity].add(Sample(ordinal, value[0], count), bound)
        matching += 1
    if not matching:
        raise InvalidInput("no_matching_samples")
    findings = [item for group in groups.values() for item in group.findings()]
    return {"status": "findings" if findings else "clean",
            "groups": len(groups), "samples": matching, "findings": findings}


def emit(payload, exit_code):
    remaining = memoryview(payload)
    try:
        while remaining:
            written = os.write(1, remaining)
            if written <= 0:
                return 2
            remaining = remaining[written:]
    except OSError:
        return 2
    return exit_code


def main(args):
    if args in (["-h"], ["--help"]):
        return emit(b"Usage: python classic_histogram_audit.py [--] RESPONSE.json METRIC_BASE\n", 0)
    try:
        if args[:1] == ["--"]:
            args = args[1:]
        elif args and args[0].startswith("-"):
            raise InvalidInput("usage")
        if len(args) != 2:
            raise InvalidInput("usage")
        path, metric = args
        if METRIC.fullmatch(metric) is None:
            raise InvalidInput("invalid_metric_base")
        report = audit(read_vector(path), metric)
        code = int(bool(report["findings"]))
    except InvalidInput as exc:
        report = {"status": "invalid", "code": exc.code, "row": exc.row}
        code = 2
    return emit(json.dumps(report, separators=(",", ":")).encode("ascii") + b"\n", code)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
