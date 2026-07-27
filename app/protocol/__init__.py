"""Structured protocol and capability registry."""

from app.protocol.models import (
    PROTOCOL_VERSION,
    AgentMessage,
    MessageAction,
    MessageStatus,
    ProtocolErrorCode,
    ProtocolTrace,
)
from app.protocol.registry import (
    ActionNotAcceptedError,
    AgentNotFoundError,
    AgentRegistration,
    AgentRegistry,
    AgentStatus,
    CapabilityMismatchError,
)

__all__ = [
    "PROTOCOL_VERSION",
    "ActionNotAcceptedError",
    "AgentMessage",
    "AgentNotFoundError",
    "AgentRegistration",
    "AgentRegistry",
    "AgentStatus",
    "CapabilityMismatchError",
    "MessageAction",
    "MessageStatus",
    "ProtocolErrorCode",
    "ProtocolTrace",
]
