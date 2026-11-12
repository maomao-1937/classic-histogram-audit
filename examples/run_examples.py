"""Check the full output and exit status of the README commands."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = [
    '{"status":"clean","groups":1,"samples":4,"findings":[]}',
    '{"status":"findings","groups":2,"samples":5,"findings":[{"code":"decreasing_bucket","rows":[2,1]},{"code":"count_mismatch","rows":[3,4]},{"code":"missing_infinity","rows":[5]}]}',
    '{"status":"findings","groups":1,"samples":3,"findings":[{"code":"duplicate_bucket","rows":[1,2]},{"code":"missing_infinity","rows":[1]}]}',
    '{"status":"invalid","code":"no_matching_samples","row":null}',
]


def main():
    checks = json.loads((ROOT / "checks.json").read_text(encoding="utf-8"))
    for check, expected in zip(checks, EXPECTED, strict=True):
        completed = subprocess.run([sys.executable, "-I", "-B", *check["args"]], cwd=ROOT,
                                   capture_output=True, text=True, encoding="utf-8", timeout=10)
        if (completed.returncode, completed.stdout, completed.stderr) != (check["exit"], expected + "\n", ""):
            raise SystemExit(f"example failed: {check['args'][1]} {check['args'][2]}")
    print(f"{len(checks)} examples matched expected output and exit status")


if __name__ == "__main__":
    main()
