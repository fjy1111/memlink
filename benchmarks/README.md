# Benchmark 结果说明

`benchmarks/results/` 是运行时输出目录，默认被 Git 忽略。正式运行会生成：

- `raw_runs.jsonl`、`raw_runs.csv`：每个真实任务的原始记录；
- `benchmark_summary.json`、`benchmark_summary.csv`：按实验配置汇总；
- `ablation_summary.csv`：structured 消融配置汇总；
- `stability_summary.json`：完整 structured 连续运行与资源清理结果；
- `environment.json`：不含环境变量和密钥的环境信息；
- `benchmark_report.md`：只基于真实数据生成的简要报告。

先检查原始记录、失败项和环境信息，再决定哪些结果进入正式 Git 提交。不要只提交汇总而丢弃原始数据，也不要手工修改结果来制造性能提升。

