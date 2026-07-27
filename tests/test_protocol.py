"""Structured protocol serialization and validation tests."""

import pytest
from pydantic import ValidationError

from app.protocol import (
    AgentMessage,
    MessageAction,
    MessageStatus,
    ProtocolTrace,
)


def test_agent_message_json_and_msgpack_round_trip() -> None:
    message = AgentMessage(
        task_id="task-1",
        sender="planner",
        receiver="retriever",
        action=MessageAction.RETRIEVE_EVIDENCE,
        parameters={"query": "RAG latency", "limit": 3},
        capability_required=["knowledge_retrieval"],
        semantic_state_ids=["state-1"],
        status=MessageStatus.ACCEPTED,
    )

    json_payload = message.to_json_bytes()
    msgpack_payload = message.to_msgpack_bytes()
    rebuilt = AgentMessage.from_msgpack_bytes(msgpack_payload)

    assert rebuilt == message
    assert b"state-1" in json_payload
    assert len(msgpack_payload) < len(json_payload)


def test_protocol_trace_counts_exact_serialized_bytes() -> None:
    message = AgentMessage(
        task_id="task-1",
        sender="planner",
        receiver="planner",
        action=MessageAction.HANDSHAKE,
    )
    trace = ProtocolTrace()

    trace.append(message)

    assert trace.json_serialized_bytes == len(message.to_json_bytes())
    assert trace.msgpack_serialized_bytes == len(message.to_msgpack_bytes())


def test_message_rejects_unknown_protocol_version() -> None:
    with pytest.raises(ValidationError):
        AgentMessage(
            protocol_version="9.9",
            task_id="task-1",
            sender="planner",
            receiver="retriever",
            action=MessageAction.RETRIEVE_EVIDENCE,
        )
