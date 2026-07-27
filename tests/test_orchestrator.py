"""Text workflow and metric persistence tests."""

import json
from pathlib import Path

import pytest

from app.models.domain import AgentRole, TaskCreate, TaskStatus
from app.runtime.metrics import estimate_tokens
from app.runtime.orchestrator import TextTaskOrchestrator


def test_token_estimate_rounds_up() -> None:
    assert estimate_tokens(0) == 0
    assert estimate_tokens(1) == 1
    assert estimate_tokens(5) == 2


@pytest.mark.asyncio
async def test_four_agents_run_in_order_and_save_metrics(
    metrics_dir: Path,
) -> None:
    orchestrator = TextTaskOrchestrator(metrics_dir=metrics_dir)

    result = await orchestrator.run(
        TaskCreate(
            title="企业技术故障分析",
            prompt="生产 API 的延迟突然升高，并伴随少量 HTTP 500。",
        )
    )

    assert [message.sender for message in result.messages] == [
        AgentRole.PLANNER,
        AgentRole.RETRIEVER,
        AgentRole.EXECUTOR,
        AgentRole.REVIEWER,
    ]
    assert [message.receiver for message in result.messages] == [
        AgentRole.RETRIEVER,
        AgentRole.EXECUTOR,
        AgentRole.REVIEWER,
        AgentRole.USER,
    ]
    assert result.metrics.message_count == 4
    assert result.metrics.character_count == sum(
        len(message.content) for message in result.messages
    )
    assert result.metrics.estimated_token_count == estimate_tokens(
        result.metrics.character_count
    )
    assert "最终报告" in result.final_answer

    metric_path = Path(result.metrics.metrics_file)
    assert metric_path.exists()
    persisted = json.loads(metric_path.read_text(encoding="utf-8"))
    assert persisted["task_id"] == result.task_id
    assert persisted["communication_mode"] == "text"
    assert persisted["message_count"] == 4

    record = await orchestrator.get_task(result.task_id)
    assert record is not None
    assert record.task.status is TaskStatus.COMPLETED
    assert record.result == result
