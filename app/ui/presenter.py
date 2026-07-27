"""Pure presentation transforms for Streamlit and offline UI tests."""

import json
from typing import Any

from app.models import CommunicationMode, TaskResult
from app.runtime.orchestrator import TaskOrchestrator


def summarize(value: Any, limit: int = 260) -> str:
    """Render a bounded, UTF-8-safe summary without exposing vector payloads."""

    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    compact = " ".join(rendered.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def build_agent_cards(
    result: TaskResult,
    orchestrator: TaskOrchestrator,
) -> list[dict[str, Any]]:
    """Build one truthful display card for each executed Agent."""

    cards: list[dict[str, Any]] = []
    for index, role in enumerate(result.agent_trace):
        registration = orchestrator.registry.get(role)
        if result.communication_mode is CommunicationMode.TEXT:
            message = next(
                item
                for item in result.messages
                if getattr(item, "sender", None) == role
            )
            input_value: Any = (
                result.messages[index - 1].content
                if index > 0
                else "原始任务输入"
            )
            output_value = message.content
            action = "text_handoff"
            evidence_ids: list[str] = []
        else:
            protocol = next(
                (
                    item
                    for item in result.protocol_messages
                    if item["receiver"] == role
                    and item["action"] != "handshake"
                ),
                {},
            )
            input_value = protocol.get("parameters", {})
            action = protocol.get("action", "unknown")
            evidence_ids = list(protocol.get("evidence_ids", []))
            output_value = (
                result.final_answer
                if role == "reviewer"
                else protocol.get("result_ref")
                or protocol.get("parameters", {})
            )
        cards.append(
            {
                "agent": registration.name,
                "role": role,
                "capabilities": registration.capabilities,
                "action": action,
                "input_summary": summarize(input_value),
                "output_summary": summarize(output_value),
                "duration_ms": result.metrics.agent_execution_time.get(
                    role,
                    0.0,
                ),
                "status": "completed",
                "evidence_ids": evidence_ids,
            }
        )
    return cards


def build_memory_rows(
    result: TaskResult,
    orchestrator: TaskOrchestrator,
) -> list[dict[str, Any]]:
    """Resolve reused memory metadata without exposing full stored content."""

    rows: list[dict[str, Any]] = []
    for memory_id in result.reused_memory_ids:
        memory = orchestrator.memory_store.get(memory_id)
        rows.append(
            {
                "memory_id": memory.memory_id,
                "memory_type": memory.memory_type.value,
                "summary": memory.summary,
                "usage_count": memory.usage_count,
                "confidence": memory.confidence,
            }
        )
    return rows


def build_semantic_state_rows(
    result: TaskResult,
    orchestrator: TaskOrchestrator,
) -> list[dict[str, Any]]:
    """Resolve transferred state metadata while never loading vector values."""

    state_ids: list[str] = []
    for message in result.protocol_messages:
        for state_id in message.get("semantic_state_ids", []):
            if state_id not in state_ids:
                state_ids.append(state_id)
    rows: list[dict[str, Any]] = []
    for state_id in state_ids:
        state = orchestrator.state_store.get_metadata(state_id)
        rows.append(
            {
                "state_id": state.state_id,
                "dimensions": state.dimensions,
                "dtype": state.dtype,
                "byte_size": state.byte_size,
                "source_agent": state.source_agent,
                "semantic_type": state.semantic_type,
                "content_hash": state.content_hash,
            }
        )
    return rows


def benchmark_table_rows(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the exact metrics shown in the Benchmark tab."""

    rows: list[dict[str, Any]] = []
    for item in summary:
        metrics = item["metrics"]
        rows.append(
            {
                "experiment": item["experiment_name"],
                "runs": item["run_count"],
                "completion_rate": item["completion_rate"],
                "characters": metrics["text_character_count"]["mean"],
                "tokens": metrics["estimated_token_count"]["mean"],
                "json_bytes": metrics["json_serialized_bytes"]["mean"],
                "msgpack_bytes": metrics["msgpack_serialized_bytes"]["mean"],
                "p50_ms": metrics["total_duration_ms"]["p50"],
                "p95_ms": metrics["total_duration_ms"]["p95"],
                "memory_hit_rate": item["average_memory_hit_rate"],
            }
        )
    return rows

