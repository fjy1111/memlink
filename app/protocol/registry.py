"""Agent registration, capability discovery, and action validation."""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.protocol.models import (
    AgentMessage,
    MessageAction,
    MessageStatus,
    ProtocolErrorCode,
)

logger = get_logger(__name__)


class AgentStatus(StrEnum):
    """Availability state advertised by an agent."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class AgentRegistration(BaseModel):
    """Machine-readable capabilities and contracts for one agent."""

    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    accepted_actions: list[MessageAction] = Field(min_length=1)
    input_model: str = Field(min_length=1)
    output_model: str = Field(min_length=1)
    allowed_tools: list[str] = Field(default_factory=list)
    version: str = "1.0.0"
    status: AgentStatus = AgentStatus.ACTIVE


class RegistryError(RuntimeError):
    """Base error for registry and routing failures."""

    error_code: ProtocolErrorCode = ProtocolErrorCode.EXECUTION_FAILED


class AgentNotFoundError(RegistryError):
    """Raised when an agent identifier does not exist."""

    error_code = ProtocolErrorCode.AGENT_NOT_FOUND


class CapabilityMismatchError(RegistryError):
    """Raised when no active agent offers a required capability."""

    error_code = ProtocolErrorCode.CAPABILITY_MISMATCH


class ActionNotAcceptedError(RegistryError):
    """Raised when a target refuses the requested protocol action."""

    error_code = ProtocolErrorCode.ACTION_NOT_ACCEPTED


class AgentRegistry:
    """In-process registry used by the structured orchestrator."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentRegistration] = {}

    def register(self, registration: AgentRegistration) -> None:
        """Register a unique agent and preserve its validated contract."""

        if registration.agent_id in self._agents:
            raise ValueError(f"Agent {registration.agent_id!r} is already registered")
        self._agents[registration.agent_id] = registration.model_copy(deep=True)
        logger.info("Registered agent %s", registration.agent_id)

    def get(self, agent_id: str) -> AgentRegistration:
        """Return one registered agent."""

        try:
            return self._agents[agent_id].model_copy(deep=True)
        except KeyError as exc:
            raise AgentNotFoundError(f"Agent {agent_id!r} was not found") from exc

    def all(self) -> list[AgentRegistration]:
        """Return every registered agent in insertion order."""

        return [registration.model_copy(deep=True) for registration in self._agents.values()]

    def discover(self, capability: str) -> list[AgentRegistration]:
        """Find active agents that explicitly advertise a capability."""

        return [
            registration.model_copy(deep=True)
            for registration in self._agents.values()
            if registration.status is AgentStatus.ACTIVE
            and capability in registration.capabilities
        ]

    def require_capability(
        self,
        capability: str,
        action: MessageAction,
    ) -> AgentRegistration:
        """Resolve one capable agent and verify that it accepts the action."""

        candidates = self.discover(capability)
        if not candidates:
            raise CapabilityMismatchError(
                f"No active agent provides capability {capability!r}"
            )
        for registration in candidates:
            if action in registration.accepted_actions:
                return registration
        raise ActionNotAcceptedError(
            f"Agents with capability {capability!r} do not accept action {action.value!r}"
        )

    def validate_message(self, message: AgentMessage) -> None:
        """Validate receiver capabilities and action before delivery."""

        receiver = self.get(message.receiver)
        if message.action not in receiver.accepted_actions:
            raise ActionNotAcceptedError(
                f"Agent {receiver.agent_id!r} does not accept {message.action.value!r}"
            )
        missing = [
            capability
            for capability in message.capability_required
            if capability not in receiver.capabilities
        ]
        if missing:
            raise CapabilityMismatchError(
                f"Agent {receiver.agent_id!r} lacks capabilities {missing}"
            )

    def build_handshake_messages(self, task_id: str) -> list[AgentMessage]:
        """Create the minimal capability exchange recorded for a task."""

        messages: list[AgentMessage] = []
        correlation_id = task_id
        for registration in self._agents.values():
            messages.append(
                AgentMessage(
                    task_id=task_id,
                    correlation_id=correlation_id,
                    sender=registration.agent_id,
                    receiver=registration.agent_id,
                    action=MessageAction.HANDSHAKE,
                    parameters={
                        "capabilities": registration.capabilities,
                        "accepted_actions": [
                            action.value for action in registration.accepted_actions
                        ],
                        "input_model": registration.input_model,
                        "output_model": registration.output_model,
                        "allowed_tools": registration.allowed_tools,
                    },
                    capability_required=[],
                    status=MessageStatus.COMPLETED,
                )
            )
        return messages
