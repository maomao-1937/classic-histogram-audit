# Classic Histogram Audit

Check the bucket counts and total of a classic Prometheus histogram from a saved instant-query response. The JSON report points to the offending response rows, so a test can catch inconsistent data before a dashboard relies on it.

## English

Requires Python 3.11 or newer. The CLI uses the standard library and needs no packages, credentials, or configuration files. Run from the repository root. The examples were tested on Windows with Python 3.11.15. GitHub Actions also runs the same commands with Python 3.11 on Ubuntu and Windows.

~~~sh
python classic_histogram_audit.py examples/clean.json request_seconds
python classic_histogram_audit.py examples/inconsistent.json request_seconds
python classic_histogram_audit.py examples/duplicate.json request_seconds
python classic_histogram_audit.py examples/clean.json missing_metric
~~~

Expected standard output, one line per command.

~~~json
{"status":"clean","groups":1,"samples":4,"findings":[]}
{"status":"findings","groups":2,"samples":5,"findings":[{"code":"decreasing_bucket","rows":[2,1]},{"code":"count_mismatch","rows":[3,4]},{"code":"missing_infinity","rows":[5]}]}
{"status":"findings","groups":1,"samples":3,"findings":[{"code":"duplicate_bucket","rows":[1,2]},{"code":"missing_infinity","rows":[1]}]}
{"status":"invalid","code":"no_matching_samples","row":null}
~~~

The exit statuses above are **0**, **1**, **1**, and **2**, respectively. Use **0** for clean, **1** for findings, and **2** for invalid input, invalid usage, or unavailable output. The JSON uses one-based positions in the entire response vector. For **decreasing_bucket**, the first row is the lower numeric bound even if it appears later in the file. **count_mismatch** lists the +Inf row first. Missing fields point to the first row of the affected group. Duplicate and timestamp findings point to the first row and the conflicting row. Arithmetic is skipped for groups with duplicate components or mixed sample timestamps.

For your data, save the full JSON API response for an instant selector such as `request_seconds_bucket or request_seconds_count`. Pass the local response path and the metric base `request_seconds`. Matching rows need the raw series names in `__name__`. Bucket and count series group by their exact remaining label pairs after excluding `__name__` and `le`. Unrelated rows with valid labels are skipped. Numeric comparisons use the decimal values represented in the response. Equivalent bounds such as `1` and `1.0` are duplicates.

Use a trusted local regular UTF-8 JSON file up to 2 MiB and 10,000 vector rows, with the ordinary Prometheus ASCII metric name syntax (up to 200 characters). On Windows, explicit UNC and device paths and alternate data streams are rejected. File links and mounted drives depend on the filesystem, so use paths you know resolve locally. Selected rows use a numeric JSON timestamp and a nonnegative decimal count string, with decimal or scientific notation. Bounds are signed decimals or the literal **+Inf**. Decimal text is limited to 64 characters and absolute exponents to 10,000. The audit covers a single unaggregated classic histogram snapshot. Range vectors, native histograms, TSDB scans, live queries and quantile calculation are outside its scope. The report contains row numbers and finding codes without label data or input paths. Keep the original response for investigating findings.

## 中文

这个命令行工具从保存的 Prometheus 即时查询结果中检查经典直方图。它按标签组合分组，检查累积桶计数是否随上界单调不减、是否有重复或缺失的桶和总计数，以及 **+Inf** 桶是否等于 **_count**。报告保留原始向量中从 1 开始的行号，便于回到源文件定位。

使用 Python 3.11 或更新版本。在仓库根目录执行上面的命令，无需安装依赖、配置文件或凭据。前四条命令依次返回 **0**（通过）、**1**（发现问题）、**1**（发现问题）、**2**（没有可检查的样本）。本地实测环境为 Windows、Python 3.11.15。CI 在 Ubuntu 和 Windows 上运行同样的测试和示例。

处理自己的数据时，保存即时查询如 **request_seconds_bucket or request_seconds_count** 的完整 JSON 响应，传入文件路径和指标基名 **request_seconds**。按原始标签精确匹配桶与总计数，支持数值等价的边界，例如 **1** 和 **1.0**。同组时间戳不一致或有重复项时，报告行号并跳过该组的计数比较。输入为可信的本地常规 UTF-8 JSON 文件，限制为 2 MiB、10,000 行。Windows 下拒绝显式 UNC、设备路径及备用数据流，文件链接和挂载盘的实际位置由文件系统决定。支持单个未聚合的经典直方图快照。

## Tests and provenance

~~~sh
python -I -B -m unittest discover -s tests -v
python -I examples/run_examples.py
~~~

See [TESTING.md](TESTING.md) and [RESEARCH.md](RESEARCH.md) for the cases and source materials. The code and fixtures are original. Licensed under [MIT](LICENSE).
