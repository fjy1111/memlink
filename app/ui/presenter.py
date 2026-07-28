"""Pure presentation transforms for Streamlit and offline UI tests."""

import json
from typing import Any

import altair as alt

from app.models import CommunicationMode, TaskResult
from app.runtime.orchestrator import TaskOrchestrator

BENCHMARK_EXPERIMENT_LABELS = {
    "text": "text",
    "structured": "structured",
    "structured_no_memory": "no_memory",
    "structured_no_semantic_state": "no_semantic_state",
    "structured_no_result_ref": "no_result_ref",
}
BENCHMARK_CHART_HEIGHT = 360


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


def build_benchmark_chart(
    rows: list[dict[str, Any]],
    series: tuple[tuple[str, str], ...],
    *,
    y_axis_title: str,
    axis_format: str | None = None,
    tooltip_format: str = ",.3f",
) -> alt.Chart:
    """Build a screenshot-friendly comparison chart without changing data."""

    values: list[dict[str, Any]] = []
    display_order: list[str] = []
    for row in rows:
        experiment = str(row["experiment"])
        display_name = BENCHMARK_EXPERIMENT_LABELS.get(
            experiment,
            experiment,
        )
        if display_name not in display_order:
            display_order.append(display_name)
        for field, label in series:
            values.append(
                {
                    "experiment": experiment,
                    "experiment_display": display_name,
                    "metric": label,
                    "value": row[field],
                }
            )

    y_axis = alt.Axis(format=axis_format) if axis_format else alt.Axis()
    return (
        alt.Chart(alt.Data(values=values))
        .mark_bar()
        .encode(
            x=alt.X(
                "experiment_display:N",
                title="实验组",
                sort=display_order,
                axis=alt.Axis(
                    labelAngle=0,
                    labelLimit=170,
                    labelOverlap=False,
                    labelPadding=10,
                    labelFontSize=12,
                    titlePadding=14,
                    titleFontSize=13,
                ),
            ),
            xOffset=alt.XOffset("metric:N"),
            y=alt.Y(
                "value:Q",
                title=y_axis_title,
                axis=y_axis,
            ),
            color=alt.Color(
                "metric:N",
                title=None,
                legend=alt.Legend(
                    orient="top",
                    direction="horizontal",
                    labelFontSize=12,
                ),
            ),
            tooltip=[
                alt.Tooltip(
                    "experiment:N",
                    title="原始 experiment",
                ),
                alt.Tooltip("metric:N", title="指标"),
                alt.Tooltip(
                    "value:Q",
                    title="数值",
                    format=tooltip_format,
                ),
            ],
        )
        .properties(
            height=BENCHMARK_CHART_HEIGHT,
            padding={
                "left": 5,
                "right": 15,
                "top": 10,
                "bottom": 20,
            },
        )
        .configure_view(strokeWidth=0)
    )
