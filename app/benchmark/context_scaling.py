"""Offline context-growth evidence experiment for MemLink communication."""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from time import perf_counter

import numpy as np

from app.benchmark.evidence_charts import generate_context_figures
from app.benchmark.evidence_common import (
    DEFAULT_EVIDENCE_RESULTS_DIR,
    RecordingFakeLLMClient,
    build_context_task,
    describe_selected,
    encoded_message_bytes,
    ensure_output_files_available,
    estimate_tokens,
    flatten_group_summary,
    nested_group_summary,
    normalize_message_set,
    payload_strings,
    repeated_fragment_bytes,
    result_reference_metrics,
    state_reference_bytes,
    task_semantics,
    utf8_size,
    validate_evidence_output_dir,
    write_raw_and_summaries,
)
from app.benchmark.evidence_models import (
    ContextScalingRecord,
    EvidenceExperimentArtifacts,
)
from app.llm import FakeEmbeddingClient
from app.models import CommunicationMode, TaskCreate
from app.runtime.orchestrator import TaskOrchestrator

ProgressCallback = Callable[[str], None]
SCALES = (1, 2, 4, 8)
EXPERIMENTS = (
    ("text", CommunicationMode.TEXT, False),
    ("structured", CommunicationMode.STRUCTURED, True),
    (
        "structured_no_result_ref",
        CommunicationMode.STRUCTURED,
        False,
    ),
)
CONTEXT_METRICS = (
    "elapsed_ms",
    "message_count",
    "text_characters",
    "estimated_tokens",
    "utf8_payload_bytes",
    "json_bytes",
    "msgpack_bytes",
    "result_ref_count",
    "result_ref_payload_bytes",
    "inlined_payload_bytes",
    "repeated_payload_bytes",
    "repeated_payload_ratio",
    "semantic_state_count",
    "semantic_state_binary_bytes",
    "state_reference_bytes",
    "memory_hit_count",
)


class ContextScalingRunner:
    """Run semantically paired tasks with one isolated runtime per record."""

    def __init__(
        self,
        *,
        progress: ProgressCallback | None = None,
    ) -> None:
        self._progress = progress or (lambda message: None)

    async def run(
        self,
        *,
        rounds: int = 10,
        seed: int = 2026,
        output_dir: Path = DEFAULT_EVIDENCE_RESULTS_DIR,
        overwrite: bool = False,
        temporary_root: Path | None = None,
    ) -> EvidenceExperimentArtifacts:
        """Execute and persist all context scales without touching old results."""

        if rounds < 1:
            raise ValueError("rounds must be at least 1")
        destination = validate_evidence_output_dir(output_dir)
        files = {
            "raw_csv": destination / "context_scaling_raw.csv",
            "summary_csv": destination / "context_scaling_summary.csv",
            "summary_json": destination / "context_scaling_summary.json",
            "report": destination / "context_scaling_report.md",
        }
        ensure_output_files_available(files.values(), overwrite=overwrite)
        destination.mkdir(parents=True, exist_ok=True)
        if temporary_root is not None:
            temporary_root.mkdir(parents=True, exist_ok=True)

        records: list[ContextScalingRecord] = []
        cleanup_checks: list[bool] = []
        total = len(SCALES) * len(EXPERIMENTS) * rounds
        completed = 0
        for scale in SCALES:
            for round_index in range(1, rounds + 1):
                paired_tasks = [
                    build_context_task(scale, mode=mode)[0]
                    for _, mode, _ in EXPERIMENTS
                ]
                semantics = {task_semantics(task) for task in paired_tasks}
                if len(semantics) != 1:
                    raise RuntimeError(
                        "text 与 structured 未使用语义等价任务"
                    )
                for experiment, mode, enable_result_reference in EXPERIMENTS:
                    completed += 1
                    self._progress(
                        f"[context] {completed}/{total} "
                        f"{scale}x {experiment} round={round_index}"
                    )
                    random.seed(seed + scale * 1000 + round_index)
                    np.random.seed(seed + scale * 1000 + round_index)
                    task, fragments = build_context_task(scale, mode=mode)
                    record, cleaned = await self._run_once(
                        task=task,
                        fragments=fragments,
                        experiment=experiment,
                        round_index=round_index,
                        enable_result_reference=enable_result_reference,
                        temporary_root=temporary_root,
                    )
                    records.append(record)
                    cleanup_checks.append(cleaned)

        summary_rows, summary_payload = _summarize(records)
        write_raw_and_summaries(
            raw_path=files["raw_csv"],
            summary_csv_path=files["summary_csv"],
            summary_json_path=files["summary_json"],
            records=records,
            summary_rows=summary_rows,
            summary_payload=summary_payload,
        )
        files["report"].write_text(
            _build_report(records, rounds),
            encoding="utf-8",
            newline="\n",
        )
        figure_files = generate_context_figures(
            records,
            destination / "figures",
        )
        return EvidenceExperimentArtifacts(
            record_count=len(records),
            task_execution_count=len(records),
            output_files=files,
            figure_files=figure_files,
            cleanup_success=all(cleanup_checks),
            metadata={
                "backend": "fake",
                "seed": seed,
                "rounds": rounds,
                "scales": [f"{scale}x" for scale in SCALES],
                "experiments": [item[0] for item in EXPERIMENTS],
            },
        )

    async def _run_once(
        self,
        *,
        task: TaskCreate,
        fragments: list[str],
        experiment: str,
        round_index: int,
        enable_result_reference: bool,
        temporary_root: Path | None,
    ) -> tuple[ContextScalingRecord, bool]:
        runtime_path: Path
        started = perf_counter()
        with tempfile.TemporaryDirectory(
            prefix=f"memlink-evidence-context-{experiment}-",
            dir=str(temporary_root) if temporary_root else None,
        ) as temporary_name:
            runtime_path = Path(temporary_name)
            recording_llm = RecordingFakeLLMClient()
            orchestrator = TaskOrchestrator(
                metrics_dir=runtime_path / "metrics",
                state_dir=runtime_path / "states",
                memory_db_path=runtime_path / "memory" / "shared.db",
                llm=recording_llm,
                embedding=FakeEmbeddingClient(),
                backend_name="fake",
                enable_shared_memory=False,
                enable_semantic_state=(
                    getattr(task, "mode") is CommunicationMode.STRUCTURED
                ),
                enable_result_reference=enable_result_reference,
            )
            result = await orchestrator.run(task)
            message_set = normalize_message_set(
                mode=result.communication_mode,
                messages=result.messages,
                protocol_messages=result.protocol_messages,
            )
            json_bytes, msgpack_bytes = encoded_message_bytes(message_set)
            strings = payload_strings(
                mode=result.communication_mode,
                messages=message_set,
            )
            utf8_payload_bytes = utf8_size(strings)
            repeated_bytes = repeated_fragment_bytes(strings, fragments)
            if result.communication_mode is CommunicationMode.TEXT:
                result_ref_count = 0
                result_ref_bytes = 0
                inline_bytes = utf8_payload_bytes
            else:
                (
                    result_ref_count,
                    result_ref_bytes,
                    inline_bytes,
                ) = result_reference_metrics(message_set)
            protocol_state_bytes = state_reference_bytes(message_set)
            _validate_references(orchestrator, message_set)
            _validate_states(orchestrator, message_set)
            record = ContextScalingRecord(
                experiment=experiment,
                context_scale=f"{len(fragments) // 4}x",
                round=round_index,
                task_id=result.task_id,
                success=True,
                elapsed_ms=result.metrics.total_duration_ms,
                message_count=len(message_set),
                text_characters=sum(len(value) for value in strings),
                estimated_tokens=estimate_tokens(
                    sum(len(value) for value in strings)
                ),
                utf8_payload_bytes=utf8_payload_bytes,
                json_bytes=json_bytes,
                msgpack_bytes=msgpack_bytes,
                result_ref_count=result_ref_count,
                result_ref_payload_bytes=result_ref_bytes,
                inlined_payload_bytes=inline_bytes,
                repeated_payload_bytes=repeated_bytes,
                repeated_payload_ratio=(
                    repeated_bytes / utf8_payload_bytes
                    if utf8_payload_bytes
                    else 0.0
                ),
                semantic_state_count=(
                    result.metrics.semantic_state_transfer_count
                ),
                semantic_state_binary_bytes=(
                    result.metrics.semantic_state_bytes
                ),
                state_reference_bytes=protocol_state_bytes,
                memory_hit_count=result.metrics.memory_hit_count,
            )
            del recording_llm
        cleaned = not runtime_path.exists()
        if not cleaned:
            raise RuntimeError(
                f"上下文实验临时目录未清理：{runtime_path}"
            )
        if record.elapsed_ms <= 0:
            record.elapsed_ms = (perf_counter() - started) * 1000
        return record, cleaned


def _validate_references(
    orchestrator: TaskOrchestrator,
    messages: Sequence[dict[str, object]],
) -> None:
    references = {
        str(message["result_ref"])
        for message in messages
        if message.get("result_ref")
    }
    result_store = getattr(orchestrator, "_result_refs", {})
    missing = sorted(reference for reference in references if reference not in result_store)
    if missing:
        raise RuntimeError(f"result_ref 未指向真实对象：{missing}")


def _validate_states(
    orchestrator: TaskOrchestrator,
    messages: Sequence[dict[str, object]],
) -> None:
    state_ids = {
        str(state_id)
        for message in messages
        for state_id in message.get("semantic_state_ids", [])  # type: ignore[union-attr]
    }
    for state_id in state_ids:
        orchestrator.state_store.load(state_id)


def _summarize(
    records: Sequence[ContextScalingRecord],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[ContextScalingRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.experiment, record.context_scale)].append(record)
    csv_rows: list[dict[str, object]] = []
    json_rows: list[dict[str, object]] = []
    for experiment, _, _ in EXPERIMENTS:
        for scale in (f"{value}x" for value in SCALES):
            rows = grouped[(experiment, scale)]
            metrics = describe_selected(rows, CONTEXT_METRICS)
            dimensions = {
                "experiment": experiment,
                "context_scale": scale,
            }
            success_rate = sum(row.success for row in rows) / len(rows)
            csv_rows.append(
                flatten_group_summary(
                    dimensions=dimensions,
                    run_count=len(rows),
                    success_rate=success_rate,
                    metrics=metrics,
                )
            )
            json_rows.append(
                nested_group_summary(
                    dimensions=dimensions,
                    run_count=len(rows),
                    success_rate=success_rate,
                    metrics=metrics,
                )
            )
    return csv_rows, json_rows


def _build_report(
    records: Sequence[ContextScalingRecord],
    rounds: int,
) -> str:
    means: dict[tuple[str, str], dict[str, float]] = {}
    for experiment, _, _ in EXPERIMENTS:
        for scale in (f"{value}x" for value in SCALES):
            rows = [
                record
                for record in records
                if record.experiment == experiment
                and record.context_scale == scale
            ]
            means[(experiment, scale)] = {
                "utf8": sum(row.utf8_payload_bytes for row in rows) / len(rows),
                "json": sum(row.json_bytes for row in rows) / len(rows),
                "msgpack": sum(row.msgpack_bytes for row in rows) / len(rows),
                "repeat": sum(row.repeated_payload_bytes for row in rows)
                / len(rows),
                "elapsed": sum(row.elapsed_ms for row in rows) / len(rows),
                "messages": sum(row.message_count for row in rows) / len(rows),
            }
    short_text = means[("text", "1x")]
    short_structured = means[("structured", "1x")]
    if short_structured["json"] > short_text["json"]:
        fixed_observation = (
            f"1x 时 structured 的 JSON 总字节为 "
            f"{short_structured['json']:.1f}，高于 text 的 "
            f"{short_text['json']:.1f}，观察到短上下文的总字节固定开销。"
        )
    else:
        fixed_observation = (
            f"1x 时 structured 的 JSON 总字节为 "
            f"{short_structured['json']:.1f}，低于 text 的 "
            f"{short_text['json']:.1f}，本组数据未观察到 structured 的"
            "总字节固定劣势；但其消息数和本地耗时仍体现固定协议成本。"
        )
    ref_benefit_scales = [
        scale
        for scale in (f"{value}x" for value in SCALES)
        if means[("structured", scale)]["json"]
        < means[("structured_no_result_ref", scale)]["json"]
    ]
    first_benefit = ref_benefit_scales[0] if ref_benefit_scales else "未观察到"
    lines = [
        "# MemLink 上下文规模增长证据实验",
        "",
        "本报告由 Fake 后端离线实测结果自动生成，不包含预设优势结论。",
        "",
        f"- 实验记录：{len(records)} 条（每组每规模 {rounds} 轮）",
        "- 每条记录使用独立临时 SQLite、状态目录和指标目录。",
        "- text、structured、structured_no_result_ref 使用完全相同的任务语义和故障资料。",
        "",
        "| 规模 | 实验 | 消息数 | UTF-8载荷(B) | JSON(B) | MessagePack(B) | 重复载荷(B) | 平均耗时(ms) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for scale in (f"{value}x" for value in SCALES):
        for experiment, _, _ in EXPERIMENTS:
            value = means[(experiment, scale)]
            lines.append(
                f"| {scale} | {experiment} | {value['messages']:.1f} | "
                f"{value['utf8']:.1f} | {value['json']:.1f} | "
                f"{value['msgpack']:.1f} | {value['repeat']:.1f} | "
                f"{value['elapsed']:.3f} |"
            )
    lines.extend(
        [
            "",
            "## 客观结论",
            "",
            f"- {fixed_observation}",
            f"- 1x 时 structured/text 的平均消息数为 "
            f"{short_structured['messages']:.1f}/"
            f"{short_text['messages']:.1f}，平均耗时为 "
            f"{short_structured['elapsed']:.3f}/"
            f"{short_text['elapsed']:.3f} ms；structured 没有获得耗时改善。",
            f"- result_ref 相比完整内联首次出现 JSON 总字节收益的规模：{first_benefit}。",
            "- MessagePack 和 JSON 均由同一批实际消息编码；该数据是编码体积证据，"
            "不代表当前单进程运行发生了真实网络传输。",
            "- SemanticState 二进制大小与协议中的 state_id UTF-8 字节分开记录，"
            "未把 .npy 文件容器大小当作通信字节。",
            "- elapsed_ms 包含 Agent、状态和本地存储开销，不解释为纯网络延迟。",
            "- 若 structured 在某些规模没有降低总载荷或耗时，应以表中数据为准，"
            "不能概括为所有任务均显著提升。",
            "",
            "## 指标口径",
            "",
            "- `utf8_payload_bytes`：实际消息载荷中字符串值的 UTF-8 字节总和。",
            "- `json_bytes` / `msgpack_bytes`：同一批实际消息分别编码后的字节总和。",
            "- `repeated_payload_bytes`：每个确定性故障证据片段在消息载荷中首次出现后，"
            "其所有精确重复出现的 UTF-8 字节总和。",
            "- `inlined_payload_bytes`：text 的完整消息正文，或 structured 中完整结果"
            "字段的紧凑 JSON 字节。",
            "- `result_ref_payload_bytes`：协议顶层及参数字段中结果引用字符串的 UTF-8 字节。",
            "- `semantic_state_binary_bytes`：被 state_id 引用的 NumPy 向量原始二进制字节。",
            "- `state_reference_bytes`：协议消息中 state_id 字符串的 UTF-8 字节。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.benchmark.context_scaling"
    )
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_EVIDENCE_RESULTS_DIR,
    )
    parser.add_argument("--temporary-root", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser


async def _async_main(arguments: argparse.Namespace) -> int:
    runner = ContextScalingRunner(progress=print)
    artifacts = await runner.run(
        rounds=arguments.rounds,
        seed=arguments.seed,
        output_dir=arguments.output_dir,
        overwrite=arguments.overwrite,
        temporary_root=arguments.temporary_root,
    )
    print(
        f"上下文规模实验完成：{artifacts.record_count} 条记录，"
        f"backend=fake，cleanup={artifacts.cleanup_success}"
    )
    for name, path in artifacts.output_files.items():
        print(f"{name}: {path}")
    for path in artifacts.figure_files:
        print(f"figure: {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    return asyncio.run(_async_main(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
