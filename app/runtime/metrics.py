"""Stage-one baseline metric calculation and JSON persistence."""

import json
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.models.domain import (
    CommunicationMode,
    RunMetrics,
    TaskStatus,
    TextMessage,
)
from app.protocol import ProtocolTrace

logger = get_logger(__name__)


def estimate_tokens(character_count: int) -> int:
    """Estimate tokens consistently without calling a tokenizer service."""

    if character_count <= 0:
        return 0
    return (character_count + 3) // 4


class MetricsWriter:
    """Persist one UTF-8 JSON metric artifact for every completed task."""

    def __init__(self, metrics_dir: Path) -> None:
        self._metrics_dir = metrics_dir

    def save(
        self,
        task_id: str,
        elapsed_ms: float,
        messages: list[TextMessage],
        *,
        mode: CommunicationMode = CommunicationMode.TEXT,
        protocol_trace: ProtocolTrace | None = None,
        semantic_state_transfer_count: int = 0,
        semantic_state_bytes: int = 0,
        memory_query_count: int = 0,
        memory_hit_count: int = 0,
        memory_query_hit_count: int = 0,
        reused_memory_ids: list[str] | None = None,
        repeated_retrieval_count: int = 0,
        agent_execution_time: dict[str, float] | None = None,
        retry_count: int = 0,
        error_count: int = 0,
        task_status: TaskStatus = TaskStatus.COMPLETED,
    ) -> RunMetrics:
        """Calculate exact raw metrics without drawing benchmark conclusions."""

        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        if mode is CommunicationMode.TEXT:
            character_count = sum(len(message.content) for message in messages)
            message_count = len(messages)
            json_serialized_bytes = sum(
                len(message.model_dump_json().encode("utf-8"))
                for message in messages
            )
            msgpack_serialized_bytes = 0
        else:
            trace = protocol_trace or ProtocolTrace()
            character_count = sum(
                self._count_text_values(message.model_dump(mode="json"))
                for message in trace.messages
            )
            message_count = len(trace.messages)
            json_serialized_bytes = trace.json_serialized_bytes
            msgpack_serialized_bytes = trace.msgpack_serialized_bytes
        protocol_message_count = (
            len(protocol_trace.messages)
            if protocol_trace is not None
            else 0
        )
        result_reference_count = (
            sum(
                1
                for message in protocol_trace.messages
                if message.result_ref is not None
            )
            if protocol_trace is not None
            else 0
        )
        full_result_transfer_count = (
            sum(
                1
                for message in protocol_trace.messages
                for key in message.parameters
                if key in {
                    "task_plan",
                    "evidence_bundle",
                    "execution_result",
                    "review_result",
                }
            )
            if protocol_trace is not None
            else 0
        )
        memory_hit_rate = (
            memory_query_hit_count / memory_query_count
            if memory_query_count
            else 0.0
        )
        destination = self._metrics_dir / f"{task_id}.json"
        rounded_elapsed = round(max(elapsed_ms, 0.0), 3)
        metrics = RunMetrics(
            elapsed_ms=rounded_elapsed,
            communication_mode=mode,
            message_count=message_count,
            protocol_message_count=protocol_message_count,
            character_count=character_count,
            text_character_count=character_count,
            estimated_token_count=estimate_tokens(character_count),
            json_serialized_bytes=json_serialized_bytes,
            msgpack_serialized_bytes=msgpack_serialized_bytes,
            semantic_state_transfer_count=semantic_state_transfer_count,
            semantic_state_bytes=semantic_state_bytes,
            memory_query_count=memory_query_count,
            memory_hit_count=memory_hit_count,
            memory_hit_rate=memory_hit_rate,
            reused_memory_ids=reused_memory_ids or [],
            repeated_retrieval_count=repeated_retrieval_count,
            result_reference_count=result_reference_count,
            full_result_transfer_count=full_result_transfer_count,
            agent_execution_time={
                role: round(duration, 3)
                for role, duration in (agent_execution_time or {}).items()
            },
            total_duration_ms=rounded_elapsed,
            retry_count=retry_count,
            error_count=error_count,
            task_status=task_status,
            metrics_file=str(destination),
        )
        payload = {
            "task_id": task_id,
            **metrics.model_dump(mode="json"),
        }
        temporary = destination.with_suffix(".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(destination)
        except OSError as exc:
            logger.exception("Unable to persist metrics for task %s", task_id)
            raise RuntimeError(f"Unable to save metrics: {exc}") from exc
        logger.info("Saved task %s metrics to %s", task_id, destination)
        return metrics

    @classmethod
    def _count_text_values(cls, value: Any) -> int:
        """Count natural-language string content nested in protocol fields."""

        if isinstance(value, str):
            return len(value)
        if isinstance(value, dict):
            return sum(cls._count_text_values(item) for item in value.values())
        if isinstance(value, list):
            return sum(cls._count_text_values(item) for item in value)
        return 0
