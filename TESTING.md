# Verification

Run from the repository root with Python 3.11+.

~~~sh
python -I -B -m unittest discover -s tests -v
python -I examples/run_examples.py
~~~

The local run used a clean Windows CPython 3.11.15 environment with no additional packages. The CI workflow uses the same Python minor version on Ubuntu and Windows. Unit tests exercise the CLI subprocess, including ordered and unordered buckets, numeric duplicates, exact decimal comparisons, separate label groups, missing components, mixed timestamps, malformed rows and envelopes, input limits, and closed output pipes. The example runner verifies full stdout, empty stderr and exit status for each README example.

The test fixtures are synthetic local files. The tests establish snapshot parsing and arithmetic under the documented input limits. Production instrumentation, PromQL evaluation and live Prometheus responses are outside this test scope.
