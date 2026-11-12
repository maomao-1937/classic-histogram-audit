# Research and attribution

- The Prometheus metric type documentation explains the cumulative classic buckets and the identity of the +Inf count and total. [Prometheus metric types](https://prometheus.io/docs/concepts/metric_types/)
- The HTTP API specification defines an instant vector as objects with metric labels and a sample pair. [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/#instant-vectors)
- Issue #19426, filed August 15, 2026, describes inconsistent classic histogram series in TSDB and requests analysis of affected series. It motivated the checks for decreasing counts, mismatched totals and numeric aliases. This project tests original local fixtures and a single API snapshot. [Prometheus issue #19426](https://github.com/prometheus/prometheus/issues/19426)
- Promtool has metric validation and query commands. An instant query retrieves samples and query functions can use them to estimate quantiles. This utility starts from an already saved API result and reports where the bucket counts in that result disagree. [Promtool documentation](https://prometheus.io/docs/prometheus/latest/command-line/promtool/)

The implementation and synthetic fixtures were authored for this repository. Upstream code and issue examples are not included.
