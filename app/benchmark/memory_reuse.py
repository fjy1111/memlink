"""Offline evidence experiment for correct cross-task shared-memory reuse."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from app.benchmark.evidence_charts import generate_memory_figures
from app.benchmark.evidence_common import (
    DEFAULT_EVIDENCE_RESULTS_DIR,
    RecordingFakeLLMClient,
    describe_selected,
    ensure_output_files_available,
    flatten_group_summary,
    memory_evidence_ids,
    nested_group_summary,
    read_memory_ids,
    repeated_fragment_bytes,
    validate_evidence_output_dir,
    write_raw_and_summaries,
)
from app.benchmark.evidence_models import (
    EvidenceExperimentArtifacts,
    MemoryReuseRecord,
)
from app.core.config import PROJECT_ROOT
from app.llm import FakeEmbeddingClient
from app.models import CommunicationMode, TaskCreate
from app.runtime.orchestrator import TaskOrchestrator

ProgressCallback = Callable[[str], None]
TASKS_FILE = PROJECT_ROOT / "data" / "examples" / "continuous_tasks.json"
SCENARIOS = ("rag", "api")
CONDITIONS = (
    "no_memory",
    "cold_memory",
    "warm_memory",
    "irrelevant_memory",
)
MEMORY_METRICS = (
    "elapsed_ms",
    "message_count",
    "text_characters",
    "estimated_tokens",
    "json_bytes",
    "msgpack_bytes",
    "memory_query_count",
    "memory_hit_count",
    "memory_reuse_precision",
    "repeated_steps",
    "avoided_steps",
    "repeated_payload_bytes",
    "final_confidence",
)


class MemoryReuseRunner:
    """Run positive and negative memory controls in fresh SQLite stores."""

    def __init__(
        self,
        *,
        progress: ProgressCallback | None = None,
    ) -> None:
        self._progress = progress or (lambda message: None)
        self._scenario_tasks = _load_scenario_tasks()

    async def run(
        self,
        *,
        rounds: int = 10,
        seed: int = 2026,
        output_dir: Path = DEFAULT_EVIDENCE_RESULTS_DIR,
        overwrite: bool = False,
        temporary_root: Path | None = None,
    ) -> EvidenceExperimentArtifacts:
        """Execute all memory conditions without sharing state across rounds."""

        if rounds < 1:
            raise ValueError("rounds must be at least 1")
        destination = validate_evidence_output_dir(output_dir)
        files = {
            "raw_csv": destination / "memory_reuse_raw.csv",
            "summary_csv": destination / "memory_reuse_summary.csv",
            "summary_json": destination / "memory_reuse_summary.json",
            "report": destination / "memory_reuse_report.md",
        }
        ensure_output_files_available(files.values(), overwrite=overwrite)
        destination.mkdir(parents=True, exist_ok=True)
        if temporary_root is not None:
            temporary_root.mkdir(parents=True, exist_ok=True)

        records: list[MemoryReuseRecord] = []
        cleanup_checks: list[bool] = []
        plan_steps: dict[tuple[str, str, int], list[str]] = {}
        task_execution_count = 0
        total_records = len(SCENARIOS) * len(CONDITIONS) * rounds
        completed = 0
        for scenario in SCENARIOS:
            for condition in CONDITIONS:
                for round_index in range(1, rounds + 1):
                    completed += 1
                    self._progress(
                        f"[memory] {completed}/{total_records} "
                        f"{scenario} {condition} round={round_index}"
                    )
                    random.seed(
                        seed
                        + SCENARIOS.index(scenario) * 10_000
                        + CONDITIONS.index(condition) * 1000
                        + round_index
                    )
                    np.random.seed(
                        seed
                        + SCENARIOS.index(scenario) * 10_000
                        + CONDITIONS.index(condition) * 1000
                        + round_index
                    )
                    (
                        record,
                        cleaned,
                        steps,
                        executions,
                    ) = await self._run_once(
                        scenario=scenario,
                        condition=condition,
                        round_index=round_index,
                        temporary_root=temporary_root,
                    )
                    records.append(record)
                    cleanup_checks.append(cleaned)
                    plan_steps[(scenario, condition, round_index)] = steps
                    task_execution_count += executions

        _apply_avoided_steps(records, plan_steps)
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
            _build_report(records, rounds, task_execution_count),
            encoding="utf-8",
            newline="\n",
        )
        figure_files = generate_memory_figures(
            records,
            destination / "figures",
        )
        return EvidenceExperimentArtifacts(
            record_count=len(records),
            task_execution_count=task_execution_count,
            output_files=files,
            figure_files=figure_files,
            cleanup_success=all(cleanup_checks),
            metadata={
                "backend": "fake",
                "seed": seed,
                "rounds": rounds,
                "scenarios": list(SCENARIOS),
                "conditions": list(CONDITIONS),
                "semantic_state_enabled": False,
                "semantic_state_reason": (
                    "隔离关键词/标签共享记忆复用，避免向量检索成为混杂因素"
                ),
            },
        )

    async def _run_once(
        self,
        *,
        scenario: str,
        condition: str,
        round_index: int,
        temporary_root: Path | None,
    ) -> tuple[MemoryReuseRecord, bool, list[str], int]:
        runtime_path: Path
        task_execution_count = 0
        with tempfile.TemporaryDirectory(
            prefix=f"memlink-evidence-memory-{scenario}-{condition}-",
            dir=str(temporary_root) if temporary_root else None,
        ) as temporary_name:
            runtime_path = Path(temporary_name)
            database_path = runtime_path / "memory" / "shared.db"
            recording_llm = RecordingFakeLLMClient()
            orchestrator = TaskOrchestrator(
                metrics_dir=runtime_path / "metrics",
                state_dir=runtime_path / "states",
                memory_db_path=database_path,
                llm=recording_llm,
                embedding=FakeEmbeddingClient(),
                backend_name="fake",
                enable_shared_memory=condition != "no_memory",
                enable_semantic_state=False,
                enable_result_reference=True,
            )

            expected_memory_ids: list[str] = []
            irrelevant_memory_ids: list[str] = []
            seed_steps: list[str] = []
            if condition in {"warm_memory", "irrelevant_memory"}:
                seed_scenario = (
                    scenario
                    if condition == "warm_memory"
                    else _other_scenario(scenario)
                )
                seed_task = self._task(seed_scenario, index=0)
                before = set(read_memory_ids(database_path))
                await orchestrator.run(seed_task)
                task_execution_count += 1
                after = set(read_memory_ids(database_path))
                created = sorted(after.difference(before))
                if len(created) != 1:
                    raise RuntimeError(
                        "前置任务应写入且只写入一条可审计记忆"
                    )
                if condition == "warm_memory":
                    expected_memory_ids = created
                else:
                    irrelevant_memory_ids = created
                seed_payloads = recording_llm.response_payloads("TaskPlan")
                if seed_payloads:
                    seed_steps = [
                        str(step) for step in seed_payloads[-1].get("steps", [])
                    ]

            call_start = len(recording_llm.calls)
            target = self._task(scenario, index=1)
            result = await orchestrator.run(target)
            task_execution_count += 1
            target_calls = recording_llm.calls[call_start:]
            target_plan_payload = next(
                (
                    json.loads(call.response_payload)
                    for call in target_calls
                    if call.response_model == "TaskPlan"
                ),
                {},
            )
            target_steps = [
                str(step) for step in target_plan_payload.get("steps", [])
            ]
            retrieved_memory_ids = sorted(set(result.reused_memory_ids))
            reused_memory_ids = memory_evidence_ids(result.evidence_ids)
            relevant_reused_ids = sorted(
                set(reused_memory_ids).intersection(expected_memory_ids)
            )
            irrelevant_reused_ids = sorted(
                set(reused_memory_ids).intersection(irrelevant_memory_ids)
            )
            precision = (
                len(relevant_reused_ids) / len(reused_memory_ids)
                if reused_memory_ids
                else 0.0
            )
            retrieved_not_reused = sorted(
                set(retrieved_memory_ids).difference(reused_memory_ids)
            )
            memory_fragments: list[str] = []
            for memory_id in sorted(
                set(expected_memory_ids).union(irrelevant_memory_ids)
            ):
                memory = orchestrator.memory_store.get(memory_id)
                memory_fragments.extend([memory.summary, memory.content])
            repeated_bytes = repeated_fragment_bytes(
                [call.user_prompt for call in target_calls],
                memory_fragments,
            )
            repeated_steps = (
                len(set(seed_steps).intersection(target_steps))
                if seed_steps
                else 0
            )
            record = MemoryReuseRecord(
                scenario=scenario,
                condition=condition,
                round=round_index,
                task_id=result.task_id,
                success=True,
                elapsed_ms=result.metrics.total_duration_ms,
                message_count=result.metrics.message_count,
                text_characters=result.metrics.text_character_count,
                estimated_tokens=result.metrics.estimated_token_count,
                json_bytes=result.metrics.json_serialized_bytes,
                msgpack_bytes=result.metrics.msgpack_serialized_bytes,
                memory_query_count=result.metrics.memory_query_count,
                memory_hit_count=result.metrics.memory_hit_count,
                retrieved_memory_ids=retrieved_memory_ids,
                reused_memory_ids=reused_memory_ids,
                expected_memory_ids=expected_memory_ids,
                irrelevant_memory_ids=irrelevant_memory_ids,
                relevant_memory_reused=(
                    bool(expected_memory_ids)
                    and set(expected_memory_ids).issubset(reused_memory_ids)
                ),
                irrelevant_memory_reused=bool(irrelevant_reused_ids),
                memory_reuse_precision=precision,
                repeated_steps=repeated_steps,
                avoided_steps=0,
                repeated_payload_bytes=repeated_bytes,
                reviewer_accepted=bool(result.review_passed),
                reviewer_rejected_memory=(
                    retrieved_not_reused
                    if result.review_passed
                    else []
                ),
                final_confidence=result.review_confidence or 0.0,
            )
        cleaned = not runtime_path.exists()
        if not cleaned:
            raise RuntimeError(
                f"共享记忆实验临时目录未清理：{runtime_path}"
            )
        return record, cleaned, target_steps, task_execution_count

    def _task(self, scenario: str, *, index: int) -> TaskCreate:
        payload = self._scenario_tasks[scenario][index]
        return TaskCreate(
            title=payload["title"],
            prompt=payload["prompt"],
            task_topic=payload["task_topic"],
            mode=CommunicationMode.STRUCTURED,
        )


def _load_scenario_tasks() -> dict[str, list[dict[str, str]]]:
    payload = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    return {
        scenario: [
            {
                "title": str(task["title"]),
                "prompt": str(task["prompt"]),
                "task_topic": str(task["task_topic"]),
            }
            for task in payload["groups"][scenario]["tasks"]
        ]
        for scenario in SCENARIOS
    }


def _other_scenario(scenario: str) -> str:
    return "api" if scenario == "rag" else "rag"


def _apply_avoided_steps(
    records: Sequence[MemoryReuseRecord],
    plan_steps: dict[tuple[str, str, int], list[str]],
) -> None:
    for record in records:
        baseline = plan_steps[(record.scenario, "no_memory", record.round)]
        current = plan_steps[(record.scenario, record.condition, record.round)]
        record.avoided_steps = max(0, len(baseline) - len(current))


def _summarize(
    records: Sequence[MemoryReuseRecord],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[MemoryReuseRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.scenario, record.condition)].append(record)
    csv_rows: list[dict[str, object]] = []
    json_rows: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        for condition in CONDITIONS:
            rows = grouped[(scenario, condition)]
            metrics = describe_selected(rows, MEMORY_METRICS)
            dimensions = {"scenario": scenario, "condition": condition}
            success_rate = sum(row.success for row in rows) / len(rows)
            csv_row = flatten_group_summary(
                dimensions=dimensions,
                run_count=len(rows),
                success_rate=success_rate,
                metrics=metrics,
            )
            csv_row.update(
                {
                    "correct_reuse_rate": sum(
                        row.relevant_memory_reused for row in rows
                    )
                    / len(rows),
                    "irrelevant_reuse_rate": sum(
                        row.irrelevant_memory_reused for row in rows
                    )
                    / len(rows),
                    "reviewer_acceptance_rate": sum(
                        row.reviewer_accepted for row in rows
                    )
                    / len(rows),
                }
            )
            json_row = nested_group_summary(
                dimensions=dimensions,
                run_count=len(rows),
                success_rate=success_rate,
                metrics=metrics,
            )
            json_row.update(
                {
                    "correct_reuse_rate": csv_row["correct_reuse_rate"],
                    "irrelevant_reuse_rate": csv_row["irrelevant_reuse_rate"],
                    "reviewer_acceptance_rate": csv_row[
                        "reviewer_acceptance_rate"
                    ],
                }
            )
            csv_rows.append(csv_row)
            json_rows.append(json_row)
    return csv_rows, json_rows


def _build_report(
    records: Sequence[MemoryReuseRecord],
    rounds: int,
    task_execution_count: int,
) -> str:
    by_condition = {
        condition: [
            record for record in records if record.condition == condition
        ]
        for condition in CONDITIONS
    }

    def mean(condition: str, field: str) -> float:
        rows = by_condition[condition]
        return sum(float(getattr(row, field)) for row in rows) / len(rows)

    warm_correct_rate = mean("warm_memory", "relevant_memory_reused")
    irrelevant_misuse_rate = mean(
        "irrelevant_memory",
        "irrelevant_memory_reused",
    )
    lines = [
        "# MemLink 共享记忆复用证据实验",
        "",
        "本报告由 Fake 后端离线实测结果自动生成。命中、实际引用和审核结果"
        "分别记录，不使用 memory_hit_count 代替正确复用。",
        "",
        f"- 目标任务记录：{len(records)} 条（每场景每条件 {rounds} 轮）",
        f"- 实际 Orchestrator 执行：{task_execution_count} 次，包含 warm/irrelevant 的前置任务。",
        "- 每个条件的每一轮均使用新的临时 SQLite 数据库。",
        "- 为隔离 Shared Memory 的确定性关键词/标签复用，本实验关闭 SemanticState；"
        "向量检索不在本实验结论范围内。",
        "",
        "| 条件 | 成功率 | 平均命中 | 正确复用率 | 无关误用率 | 重复步骤 | 避免步骤 | 重复载荷(B) | 平均耗时(ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition in CONDITIONS:
        rows = by_condition[condition]
        lines.append(
            f"| {condition} | "
            f"{sum(row.success for row in rows) / len(rows):.2%} | "
            f"{mean(condition, 'memory_hit_count'):.2f} | "
            f"{mean(condition, 'relevant_memory_reused'):.2%} | "
            f"{mean(condition, 'irrelevant_memory_reused'):.2%} | "
            f"{mean(condition, 'repeated_steps'):.2f} | "
            f"{mean(condition, 'avoided_steps'):.2f} | "
            f"{mean(condition, 'repeated_payload_bytes'):.1f} | "
            f"{mean(condition, 'elapsed_ms'):.3f} |"
        )
    warm_payload = mean("warm_memory", "repeated_payload_bytes")
    no_memory_payload = mean("no_memory", "repeated_payload_bytes")
    warm_steps = mean("warm_memory", "avoided_steps")
    lines.extend(
        [
            "",
            "## 客观结论",
            "",
            f"- warm_memory 的正确记忆复用率为 {warm_correct_rate:.2%}。",
            f"- irrelevant_memory 的无关记忆误用率为 {irrelevant_misuse_rate:.2%}。",
            "- `retrieved_memory_ids` 是检索返回，`reused_memory_ids` 只包含"
            "进入 EvidenceBundle 并继续传给 Executor/Reviewer 的 `memory:<id>`。",
            f"- warm_memory 平均避免步骤为 {warm_steps:.2f}；若为 0，表示当前"
            "确定性 Fake Planner 没有因记忆缩短固定三步计划。",
            f"- warm_memory/no_memory 的重复记忆载荷分别为 "
            f"{warm_payload:.1f}/{no_memory_payload:.1f} B。该指标没有下降时，"
            "不能宣称共享记忆减少了文本传输。",
            f"- warm_memory/no_memory 的平均耗时分别为 "
            f"{mean('warm_memory', 'elapsed_ms'):.3f}/"
            f"{mean('no_memory', 'elapsed_ms'):.3f} ms；SQLite 检索可能增加"
            "本地耗时，不能预设记忆一定更快。",
            "- `reviewer_accepted` 表示整个 ReviewResult 通过；当前协议没有逐条"
            "记忆接受字段。`reviewer_rejected_memory` 仅保存已检索但未进入证据链"
            "且最终审核通过的候选，不能解释为模型显式生成的拒绝理由。",
            "",
            "## 指标口径",
            "",
            "- `retrieved_memory_ids`：Orchestrator 多策略检索后去重并提供给 Agent 的 ID。",
            "- `reused_memory_ids`：Retriever 生成的 `memory:<id>` 证据所引用的 ID。",
            "- `expected_memory_ids`：同轮相关前置任务实际写入 SQLite 的确定性记忆 ID。",
            "- `relevant_memory_reused`：预期 ID 非空且全部进入证据链。",
            "- `irrelevant_memory_reused`：负对照预置 ID 中至少一条进入证据链。",
            "- `memory_reuse_precision`：相关复用 ID 数除以全部复用 ID 数；"
            "无复用时记为 0。",
            "- `repeated_steps`：目标计划与同轮前置任务计划完全相同的步骤数。",
            "- `avoided_steps`：同场景 no_memory 计划步骤数减去当前条件步骤数，下限为 0。",
            "- `repeated_payload_bytes`：相关或无关记忆的 summary/content 在目标任务"
            "LLM 输入中首次出现后的精确重复 UTF-8 字节。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.benchmark.memory_reuse"
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
    runner = MemoryReuseRunner(progress=print)
    artifacts = await runner.run(
        rounds=arguments.rounds,
        seed=arguments.seed,
        output_dir=arguments.output_dir,
        overwrite=arguments.overwrite,
        temporary_root=arguments.temporary_root,
    )
    print(
        f"共享记忆实验完成：{artifacts.record_count} 条记录，"
        f"{artifacts.task_execution_count} 次任务执行，"
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
