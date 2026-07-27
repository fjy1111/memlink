"""Agent registry and capability discovery tests."""

import pytest

from app.protocol import (
    ActionNotAcceptedError,
    AgentMessage,
    AgentRegistration,
    AgentRegistry,
    CapabilityMismatchError,
    MessageAction,
)


def make_registration(
    agent_id: str,
    capability: str,
    action: MessageAction,
) -> AgentRegistration:
    return AgentRegistration(
        agent_id=agent_id,
        name=agent_id.title(),
        role=agent_id,
        capabilities=[capability],
        accepted_actions=[action, MessageAction.HANDSHAKE],
        input_model="Input",
        output_model="Output",
    )


def test_registry_discovers_agent_by_capability() -> None:
    registry = AgentRegistry()
    registry.register(
        make_registration(
            "planner",
            "task_planning",
            MessageAction.PLAN_TASK,
        )
    )
    registry.register(
        make_registration(
            "retriever",
            "knowledge_retrieval",
            MessageAction.RETRIEVE_EVIDENCE,
        )
    )

    resolved = registry.require_capability(
        "knowledge_retrieval",
        MessageAction.RETRIEVE_EVIDENCE,
    )

    assert resolved.agent_id == "retriever"
    assert registry.discover("task_planning")[0].agent_id == "planner"


def test_registry_rejects_capability_and_action_mismatch() -> None:
    registry = AgentRegistry()
    registry.register(
        make_registration(
            "planner",
            "task_planning",
            MessageAction.PLAN_TASK,
        )
    )

    with pytest.raises(CapabilityMismatchError):
        registry.require_capability(
            "knowledge_retrieval",
            MessageAction.RETRIEVE_EVIDENCE,
        )

    with pytest.raises(ActionNotAcceptedError):
        registry.validate_message(
            AgentMessage(
                task_id="task-1",
                sender="reviewer",
                receiver="planner",
                action=MessageAction.REVIEW_RESULT,
            )
        )


def test_registry_builds_capability_handshake() -> None:
    registry = AgentRegistry()
    registry.register(
        make_registration(
            "planner",
            "task_planning",
            MessageAction.PLAN_TASK,
        )
    )

    messages = registry.build_handshake_messages("task-1")

    assert len(messages) == 1
    assert messages[0].action is MessageAction.HANDSHAKE
    assert messages[0].parameters["capabilities"] == ["task_planning"]
