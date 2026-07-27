"""UTF-8 benchmark artifacts and reports generated from raw records."""

import csv
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.benchmark.models import (
    BenchmarkRunRecord,
    ExperimentSummary,
    StabilitySummary,
)


def _json_value(value: Any) -> Any:
    """Serialize nested CSV values without Python repr output."""

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def write_json(path: Path, value: Any) -> None:
    """Write one indented UTF-8 JSON artifact atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_jsonl(path: Path, records: Iterable[BenchmarkRunRecord]) -> None:
    """Write every raw run as one UTF-8 JSON line."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(record.model_dump_json())
            handle.write("\n")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write Excel-compatible UTF-8-SIG CSV with stable columns."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fieldnames = list(rows[0]) if rows else []
    with temporary.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        if fieldnames:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(
                {
                    key: _json_value(value)
                    for key, value in row.items()
                }
                for row in rows
            )
    temporary.replace(path)


def flatten_summary(summary: ExperimentSummary) -> dict[str, Any]:
    """Flatten nested statistics for CSV consumers."""

    row: dict[str, Any] = {
        "experiment_name": summary.experiment_name.value,
        "communication_mode": summary.communication_mode.value,
        "run_count": summary.run_count,
        "completion_rate": summary.completion_rate,
        "error_rate": summary.error_rate,
        "average_memory_hit_rate": summary.average_memory_hit_rate,
    }
    for metric_name, metric in summary.metrics.items():
        for statistic_name, value in metric.model_dump().items():
            row[f"{metric_name}_{statistic_name}"] = value
    return row


def build_markdown_report(
    summaries: list[ExperimentSummary],
    stability: StabilitySummary | None,
) -> str:
    """Build a concise report using only measured aggregate values."""

    lines = [
        "# MemLink Benchmark Report",
        "",
        "本报告由原始运行记录自动汇总，不包含预设性能结论。",
        "",
        "| 实验 | 运行数 | 完成率 | 平均字符数 | 平均 Token | P50/P95 耗时(ms) | 平均记忆命中率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in summaries:
        duration = summary.metrics["total_duration_ms"]
        lines.append(
            "| "
            f"{summary.experiment_name.value} | "
            f"{summary.run_count} | "
            f"{summary.completion_rate:.2%} | "
            f"{summary.metrics['text_character_count'].mean:.3f} | "
            f"{summary.metrics['estimated_token_count'].mean:.3f} | "
            f"{duration.p50:.3f}/{duration.p95:.3f} | "
            f"{summary.average_memory_hit_rate:.2%} |"
        )
    lines.extend(["", "## 观测说明", ""])
    text = next(
        (
            summary
            for summary in summaries
            if summary.experiment_name.value == "text"
        ),
        None,
    )
    structured = next(
        (
            summary
            for summary in summaries
            if summary.experiment_name.value == "structured"
        ),
        None,
    )
    if text is not None and structured is not None:
        for metric in (
            "text_character_count",
            "estimated_token_count",
            "json_serialized_bytes",
            "msgpack_serialized_bytes",
            "total_duration_ms",
        ):
            text_mean = text.metrics[metric].mean
            structured_mean = structured.metrics[metric].mean
            relation = "高于" if structured_mean > text_mean else "不高于"
            lines.append(
                f"- structured 的 `{metric}` 均值为 "
                f"{structured_mean:.3f}，{relation} text 的 {text_mean:.3f}。"
            )
    else:
        lines.append("- 当前结果只包含部分实验，未生成 text/structured 对比。")
    if stability is not None:
        lines.extend(
            [
                "",
                "## 稳定性",
                "",
                f"- 连续任务数：{stability.total_tasks}",
                f"- 成功/失败：{stability.successful_tasks}/{stability.failed_tasks}",
                f"- P50/P95：{stability.p50_duration_ms:.3f}/"
                f"{stability.p95_duration_ms:.3f} ms",
                f"- 资源清理：{'成功' if stability.cleanup_success else '失败'}",
            ]
        )
    return "\n".join(lines) + "\n"


def write_all_outputs(
    *,
    results_dir: Path,
    records: list[BenchmarkRunRecord],
    summaries: list[ExperimentSummary],
    stability: StabilitySummary | None,
    environment: dict[str, Any],
) -> dict[str, Path]:
    """Persist raw, aggregate, ablation, stability, and report artifacts."""

    results_dir.mkdir(parents=True, exist_ok=True)
    output_files = {
        "raw_jsonl": results_dir / "raw_runs.jsonl",
        "raw_csv": results_dir / "raw_runs.csv",
        "summary_csv": results_dir / "benchmark_summary.csv",
        "summary_json": results_dir / "benchmark_summary.json",
        "ablation_csv": results_dir / "ablation_summary.csv",
        "stability_json": results_dir / "stability_summary.json",
        "environment_json": results_dir / "environment.json",
        "report": results_dir / "benchmark_report.md",
    }
    write_jsonl(output_files["raw_jsonl"], records)
    write_csv(
        output_files["raw_csv"],
        [record.model_dump(mode="json") for record in records],
    )
    summary_rows = [flatten_summary(summary) for summary in summaries]
    write_csv(output_files["summary_csv"], summary_rows)
    write_json(
        output_files["summary_json"],
        [summary.model_dump(mode="json") for summary in summaries],
    )
    write_csv(
        output_files["ablation_csv"],
        [
            row
            for row in summary_rows
            if row["experiment_name"] != "text"
        ],
    )
    write_json(
        output_files["stability_json"],
        stability.model_dump(mode="json") if stability is not None else {},
    )
    write_json(output_files["environment_json"], environment)
    output_files["report"].write_text(
        build_markdown_report(summaries, stability),
        encoding="utf-8",
        newline="\n",
    )
    return output_files

