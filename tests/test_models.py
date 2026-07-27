"""Domain model tests."""

import pytest
from pydantic import ValidationError

from app.models.domain import AgentRole, TaskCreate, TextMessage


def test_task_create_rejects_too_short_prompt() -> None:
    with pytest.raises(ValidationError):
        TaskCreate(prompt="bad")


def test_text_message_has_unique_identifier() -> None:
    first = TextMessage(
        task_id="task-1",
        sender=AgentRole.PLANNER,
        receiver=AgentRole.RETRIEVER,
        content="first",
    )
    second = TextMessage(
        task_id="task-1",
        sender=AgentRole.RETRIEVER,
        receiver=AgentRole.EXECUTOR,
        content="second",
    )

    assert first.message_id != second.message_id
    assert first.created_at.tzinfo is not None
