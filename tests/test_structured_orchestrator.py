"""Structured-mode integration and cross-task memory reuse tests."""

from pathlib import Path

import pytest

from app.models.domain import CommunicationMode, TaskCreate, TaskStatus
from app.protocol import MessageAction
from app.runtime.orchestrator import TaskOrchestrator


def build_orchestrator(tmp_path: Path) -> TaskOrchestrator:
    return TaskOrchestrator(
        metrics_dir=tmp_path / "metrics",
        state_dir=tmp_path / "states",
        memory_db_path=tmp_path / "memory" / "shared.db",
    )


@pytest.mark.asyncio
async def test_structured_mode_routes_by_capability_and_records_state(
    tmp_path: Path,
) -> None:
    orchestrator = build_orchestrator(tmp_path)

    result = await orchestrator.run(
        TaskCreate(
            title="RAG 服务故障",
            prompt="RAG 服务响应变慢，请分析检索和生成阶段。",
            task_topic="enterprise-rag",
            mode=CommunicationMode.STRUCTURED,
        )
    )

    actions = [message["action"] for message in result.protocol_messages]
    assert result.communication_mode is CommunicationMode.STRUCTURED
    assert result.agent_trace == ["planner", "retriever", "executor", "reviewer"]
    assert actions.count(MessageAction.HANDSHAKE.value) == 4
    assert MessageAction.PLAN_TASK.value in actions
    assert MessageAction.RETRIEVE_EVIDENCE.value in actions
    assert MessageAction.EXECUTE_ACTION.value in actions
    assert MessageAction.REVIEW_RESULT.value in actions
    assert MessageAction.TASK_COMPLETE.value in actions
    assert result.metrics.json_serialized_bytes > 0
    assert result.metrics.msgpack_serialized_bytes > 0
    assert result.metrics.semantic_state_transfer_count >= 1
    assert result.metrics.semantic_state_bytes > 0
    assert result.metrics.memory_query_count == 3
    assert list((tmp_path / "states").glob("*.npy"))
    assert (tmp_path / "memory" / "shared.db").is_file()
    serialized = str(result.protocol_messages)
    assert "array(" not in serialized
    for message in result.protocol_messages:
        assert "vector" not in message["parameters"]
        assert "embedding" not in message["parameters"]
        assert not any(
            isinstance(value, list)
            and len(value) > 8
            and all(isinstance(item, float) for item in value)
            for value in message["parameters"].values()
        )

    record = await orchestrator.get_task(result.task_id)
    assert record is not None
    assert record.task.status is TaskStatus.COMPLETED
    assert record.result == result


@pytest.mark.asyncio
async def test_later_task_reuses_actual_shared_memory(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)
    first = await orchestrator.run(
        TaskCreate(
            title="RAG 响应变慢",
            prompt="RAG 服务响应变慢，需要定位瓶颈。",
            task_topic="enterprise-rag",
            mode=CommunicationMode.STRUCTURED,
        )
    )
    second = await orchestrator.run(
        TaskCreate(
            title="RAG 高并发超时",
            prompt="高并发下 RAG 请求频繁超时，需要复用已有排查经验。",
            task_topic="enterprise-rag",
            mode=CommunicationMode.STRUCTURED,
        )
    )

    assert first.memory_hit_count == 0
    assert second.memory_hit_count > 0
    assert second.reused_memory_ids
    for memory_id in second.reused_memory_ids:
        assert orchestrator.memory_store.get(memory_id).usage_count > 0
    evidence_messages = [
        message
        for message in second.protocol_messages
        if message["action"] == MessageAction.EXECUTE_ACTION.value
    ]
    assert evidence_messages[0]["evidence_ids"]


@pytest.mark.asyncio
async def test_text_mode_still_uses_four_complete_handoffs(tmp_path: Path) -> None:
    orchestrator = build_orchestrator(tmp_path)

    result = await orchestrator.run(
        TaskCreate(
            title="API 500 故障",
            prompt="API 频繁返回 500，请给出故障分析。",
            task_topic="enterprise-api",
            mode=CommunicationMode.TEXT,
        )
    )

    assert result.communication_mode is CommunicationMode.TEXT
    assert len(result.messages) == 4
    assert result.protocol_messages == []
    assert result.metrics.message_count == 4
    assert result.metrics.msgpack_serialized_bytes == 0
    assert "最终报告" in result.final_answer
