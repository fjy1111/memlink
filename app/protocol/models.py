"""Versioned structured communication protocol for MemLink agents."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

import msgpack
from pydantic import BaseModel, Field, field_validator

from app.models.domain import utc_now

PROTOCOL_VERSION = "1.0"


class MessageAction(StrEnum):
    """Actions understood by the stage-two agent protocol."""

    HANDSHAKE = "handshake"
    CAPABILITY_EXCHANGE = "capability_exchange"
    PLAN_TASK = "plan_task"
    RETRIEVE_EVIDENCE = "retrieve_evidence"
    EXECUTE_ACTION = "execute_action"
    REVIEW_RESULT = "review_result"
    TASK_COMPLETE = "task_complete"


class MessageStatus(StrEnum):
    """Delivery or execution state of one protocol message."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    FAILED = "failed"


class ProtocolErrorCode(StrEnum):
    """Stable errors that can be returned across agent boundaries."""

    NONE = "none"
    AGENT_NOT_FOUND = "agent_not_found"
    CAPABILITY_MISMATCH = "capability_mismatch"
    ACTION_NOT_ACCEPTED = "action_not_accepted"
    INVALID_PARAMETERS = "invalid_parameters"
    EXECUTION_FAILED = "execution_failed"
    TIMEOUT = "timeout"


class AgentMessage(BaseModel):
    """A compact, traceable message exchanged in structured mode."""

    protocol_version: str = PROTOCOL_VERSION
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str = Field(min_length=1)
    parent_message_id: str | None = None
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    sender: str = Field(min_length=1)
    receiver: str = Field(min_length=1)
    action: MessageAction
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_ref: str | None = None
    capability_required: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    semantic_state_ids: list[str] = Field(default_factory=list)
    status: MessageStatus = MessageStatus.PENDING
    error_code: ProtocolErrorCode = ProtocolErrorCode.NONE
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol_version(cls, value: str) -> str:
        """Reject messages encoded for an incompatible protocol."""

        if value != PROTOCOL_VERSION:
            raise ValueError(
                f"Unsupported protocol version {value!r}; expected {PROTOCOL_VERSION}"
            )
        return value

    def to_json_bytes(self) -> bytes:
        """Serialize to canonical UTF-8 JSON bytes."""

        return self.model_dump_json(exclude_none=False).encode("utf-8")

    def to_msgpack_bytes(self) -> bytes:
        """Serialize to MessagePack without Python-specific extensions."""

        return msgpack.packb(
            self.model_dump(mode="json", exclude_none=False),
            use_bin_type=True,
        )

    @classmethod
    def from_msgpack_bytes(cls, payload: bytes) -> "AgentMessage":
        """Validate and rebuild a message from MessagePack bytes."""

        unpacked = msgpack.unpackb(payload, raw=False)
        if not isinstance(unpacked, dict):
            raise ValueError("MessagePack payload must contain a mapping")
        return cls.model_validate(unpacked)


class ProtocolTrace(BaseModel):
    """Ordered messages and their measured serialization costs."""

    messages: list[AgentMessage] = Field(default_factory=list)
    json_serialized_bytes: int = Field(default=0, ge=0)
    msgpack_serialized_bytes: int = Field(default=0, ge=0)

    def append(self, message: AgentMessage) -> None:
        """Append a message while accumulating exact byte counts."""

        self.messages.append(message)
        self.json_serialized_bytes += len(message.to_json_bytes())
        self.msgpack_serialized_bytes += len(message.to_msgpack_bytes())
