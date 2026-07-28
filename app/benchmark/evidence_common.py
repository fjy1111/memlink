"""Shared deterministic instrumentation for evidence-oriented benchmarks."""

import json
import sqlite3
import statistics
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import msgpack
from pydantic import BaseModel

from app.benchmark.models import DescriptiveStatistics
from app.benchmark.output import write_csv, write_json
from app.benchmark.statistics import describe
from app.core.config import PROJECT_ROOT
from app.llm import FakeLLMClient
from app.models import CommunicationMode, TaskCreate, TextMessage
from app.runtime.metrics import estimate_tokens

DEFAULT_EVIDENCE_RESULTS_DIR = (
    PROJECT_ROOT / "benchmarks" / "evidence_results"
)
LEGACY_RESULTS_DIR = (PROJECT_ROOT / "benchmarks" / "results").resolve()
INLINE_RESULT_KEYS = {
    "task_plan",
    "evidence_bundle",
    "execution_result",
    "review_result",
}


@dataclass(slots=True)
class RecordedLLMCall:
    """Non-sensitive request/response sizes from one Fake LLM call."""

    role: str
    response_model: str | None
    system_prompt: str
    user_prompt: str
    response_payload: str


@dataclass(slots=True)
class RecordingFakeLLMClient:
    """Delegate to the production Fake client while retaining offline evidence."""

    delegate: FakeLLMClient = field(default_factory=FakeLLMClient)
    calls: list[RecordedLLMCall] = field(default_factory=list)
    retry_count: int = 0

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str | BaseModel:
        """Record exact local prompts without performing any network request."""

        response = await self.delegate.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
            context=context,
        )
        if isinstance(response, BaseModel):
            response_payload = response.model_dump_json()
        else:
            response_payload = response
        self.calls.append(
            RecordedLLMCall(
                role=str((context or {}).get("role", "agent")),
                response_model=(
                    response_model.__name__ if response_model is not None else None
                ),
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_payload=response_payload,
            )
        )
        return response

    def response_payloads(self, model_name: str) -> list[dict[str, Any]]:
        """Return validated JSON-like payloads recorded for one schema."""

        return [
            json.loads(call.response_payload)
            for call in self.calls
            if call.response_model == model_name
        ]


def validate_evidence_output_dir(output_dir: Path) -> Path:
    """Reject the preserved stage-three result tree as an output target."""

    resolved = output_dir.resolve()
    if resolved == LEGACY_RESULTS_DIR or LEGACY_RESULTS_DIR in resolved.parents:
        raise ValueError(
            "证据实验禁止写入或覆盖 benchmarks/results"
        )
    return resolved


def ensure_output_files_available(
    paths: Iterable[Path],
    *,
    overwrite: bool,
) -> None:
    """Require explicit consent before replacing prior evidence artifacts."""

    existing = [path for path in paths if path.exists()]
    if existing and not overwrite:
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(
            f"证据实验输出已存在；使用 --overwrite 明确覆盖：{joined}"
        )


def build_context_task(
    scale: int,
    *,
    mode: CommunicationMode,
) -> tuple[TaskCreate, list[str]]:
    """Build deterministic, meaningful incident evidence at 1x/2x/4x/8x."""

    if scale not in {1, 2, 4, 8}:
        raise ValueError("context scale must be one of 1, 2, 4, 8")
    templates = (
        (
            "网关日志显示同一 trace 的排队时间持续增加，但鉴权耗时稳定；"
            "应核对入口并发、限流队列和下游连接等待。"
        ),
        (
            "检索服务 P95 从 180ms 升至 760ms，召回数量未变化；"
            "需要对照索引版本、缓存命中率和向量服务资源饱和度。"
        ),
        (
            "生成服务首 Token 延迟升高且错误率平稳；"
            "需要检查模型队列、上游超时预算和最近配置变更。"
        ),
        (
            "数据库连接池等待与请求超时同窗口上升；"
            "止损动作必须可回滚，并保留执行前后的监控对照。"
        ),
    )
    fragments: list[str] = []
    for index in range(scale * len(templates)):
        cycle = index // len(templates) + 1
        template = templates[index % len(templates)]
        fragments.append(
            f"证据片段 E{index + 1:03d}（采样批次 {cycle:02d}）：{template}"
        )
    prompt = (
        "企业 RAG 服务在高并发期间出现延迟和超时。请基于以下按时间顺序"
        "整理的真实结构化故障资料，完成证据检索、安全诊断和审核；不得跳过"
        "任何 Agent，也不得假设未给出的数据。\n"
        + "\n".join(fragments)
    )
    return (
        TaskCreate(
            title="上下文增长下的企业 RAG 故障分析",
            prompt=prompt,
            task_topic="evidence-context-scaling-rag",
            mode=mode,
        ),
        fragments,
    )


def task_semantics(task: TaskCreate) -> tuple[str, str, str | None]:
    """Return the fields that must be identical across communication modes."""

    return task.title, task.prompt, task.task_topic


def normalize_message_set(
    *,
    mode: CommunicationMode,
    messages: Sequence[TextMessage | dict[str, Any]],
    protocol_messages: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the exact observed message set used by both encoders."""

    if mode is CommunicationMode.STRUCTURED:
        return [dict(message) for message in protocol_messages]
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, TextMessage):
            normalized.append(message.model_dump(mode="json"))
        else:
            normalized.append(dict(message))
    return normalized


def encoded_message_bytes(
    messages: Sequence[dict[str, Any]],
) -> tuple[int, int]:
    """Encode the same messages to canonical JSON and MessagePack."""

    json_bytes = 0
    msgpack_bytes = 0
    for message in messages:
        json_bytes += len(
            json.dumps(
                message,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        msgpack_bytes += len(msgpack.packb(message, use_bin_type=True))
    return json_bytes, msgpack_bytes


def payload_strings(
    *,
    mode: CommunicationMode,
    messages: Sequence[dict[str, Any]],
) -> list[str]:
    """Collect scalar strings that constitute inter-agent payload values."""

    if mode is CommunicationMode.TEXT:
        return [
            str(message.get("content", ""))
            for message in messages
            if message.get("content")
        ]
    strings: list[str] = []
    for message in messages:
        for key in (
            "parameters",
            "result_ref",
            "evidence_ids",
            "semantic_state_ids",
        ):
            strings.extend(_string_values(message.get(key)))
    return strings


def utf8_size(values: Iterable[str]) -> int:
    """Return exact UTF-8 byte size without using a token estimate."""

    return sum(len(value.encode("utf-8")) for value in values)


def repeated_fragment_bytes(
    payloads: Iterable[str],
    fragments: Iterable[str],
) -> int:
    """Count bytes for exact fragment occurrences after the first occurrence."""

    materialized = list(payloads)
    repeated = 0
    for fragment in fragments:
        occurrences = sum(payload.count(fragment) for payload in materialized)
        repeated += max(0, occurrences - 1) * len(fragment.encode("utf-8"))
    return repeated


def result_reference_metrics(
    messages: Sequence[dict[str, Any]],
) -> tuple[int, int, int]:
    """Return top-level reference count, all reference bytes, inline bytes."""

    reference_count = sum(
        bool(message.get("result_ref")) for message in messages
    )
    reference_bytes = 0
    inline_bytes = 0
    for message in messages:
        top_level = message.get("result_ref")
        if isinstance(top_level, str):
            reference_bytes += len(top_level.encode("utf-8"))
        parameters = message.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for key, value in parameters.items():
            if key.endswith("_ref"):
                reference_bytes += utf8_size(_string_values(value))
            if key in INLINE_RESULT_KEYS:
                inline_bytes += len(
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
    return reference_count, reference_bytes, inline_bytes


def state_reference_bytes(messages: Sequence[dict[str, Any]]) -> int:
    """Count UTF-8 bytes of state IDs carried in protocol messages."""

    return sum(
        utf8_size(_string_values(message.get("semantic_state_ids")))
        for message in messages
    )


def read_memory_ids(database_path: Path) -> list[str]:
    """Inspect memory IDs without changing query or usage counters."""

    if not database_path.is_file():
        return []
    with closing(sqlite3.connect(database_path)) as connection:
        rows = connection.execute(
            "SELECT memory_id FROM memories ORDER BY memory_id"
        ).fetchall()
    return [str(row[0]) for row in rows]


def memory_evidence_ids(evidence_ids: Iterable[str]) -> list[str]:
    """Convert ``memory:<id>`` evidence references to actual memory IDs."""

    prefix = "memory:"
    return sorted(
        {
            evidence_id[len(prefix) :]
            for evidence_id in evidence_ids
            if evidence_id.startswith(prefix)
        }
    )


def describe_selected(
    rows: Sequence[BaseModel],
    metrics: Sequence[str],
) -> dict[str, DescriptiveStatistics]:
    """Calculate the required mean/P50/P95/population standard deviation."""

    return {
        metric: describe(
            float(getattr(row, metric)) for row in rows
        )
        for metric in metrics
    }


def flatten_group_summary(
    *,
    dimensions: dict[str, Any],
    run_count: int,
    success_rate: float,
    metrics: dict[str, DescriptiveStatistics],
) -> dict[str, Any]:
    """Flatten a grouped summary for spreadsheet consumers."""

    row = {
        **dimensions,
        "run_count": run_count,
        "success_rate": success_rate,
    }
    for metric, values in metrics.items():
        row[f"{metric}_mean"] = values.mean
        row[f"{metric}_p50"] = values.p50
        row[f"{metric}_p95"] = values.p95
        row[f"{metric}_standard_deviation"] = values.standard_deviation
    return row


def nested_group_summary(
    *,
    dimensions: dict[str, Any],
    run_count: int,
    success_rate: float,
    metrics: dict[str, DescriptiveStatistics],
) -> dict[str, Any]:
    """Build a readable JSON summary using the same calculations as CSV."""

    return {
        **dimensions,
        "run_count": run_count,
        "success_rate": success_rate,
        "metrics": {
            name: {
                "mean": values.mean,
                "p50": values.p50,
                "p95": values.p95,
                "standard_deviation": values.standard_deviation,
            }
            for name, values in metrics.items()
        },
    }


def write_raw_and_summaries(
    *,
    raw_path: Path,
    summary_csv_path: Path,
    summary_json_path: Path,
    records: Sequence[BaseModel],
    summary_rows: list[dict[str, Any]],
    summary_payload: list[dict[str, Any]],
) -> None:
    """Persist raw and aggregate evidence artifacts atomically."""

    write_csv(
        raw_path,
        [record.model_dump(mode="json") for record in records],
    )
    write_csv(summary_csv_path, summary_rows)
    write_json(summary_json_path, summary_payload)


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_string_values(item))
        return values
    if isinstance(value, (list, tuple)):
        values = []
        for item in value:
            values.extend(_string_values(item))
        return values
    return []


RecordT = TypeVar("RecordT", bound=BaseModel)


def average(rows: Sequence[RecordT], field_name: str) -> float:
    """Return a mean used by report and chart builders."""

    return statistics.fmean(float(getattr(row, field_name)) for row in rows)


__all__ = [
    "DEFAULT_EVIDENCE_RESULTS_DIR",
    "RecordingFakeLLMClient",
    "average",
    "build_context_task",
    "describe_selected",
    "encoded_message_bytes",
    "ensure_output_files_available",
    "estimate_tokens",
    "flatten_group_summary",
    "memory_evidence_ids",
    "nested_group_summary",
    "normalize_message_set",
    "payload_strings",
    "read_memory_ids",
    "repeated_fragment_bytes",
    "result_reference_metrics",
    "state_reference_bytes",
    "task_semantics",
    "utf8_size",
    "validate_evidence_output_dir",
    "write_raw_and_summaries",
]
