"""Allow-listed, deterministic tools available to Executor Agent."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)
ToolCallable = Callable[[dict[str, Any]], str]


class ToolError(RuntimeError):
    """Base error for safe tool execution."""


class ToolNotFoundError(ToolError):
    """Raised when an unregistered tool is requested."""


class ToolPermissionError(ToolError):
    """Raised when an agent is not allowed to invoke a tool."""


@dataclass(frozen=True)
class ToolDefinition:
    """One deterministic tool and its authorized roles."""

    name: str
    description: str
    allowed_roles: frozenset[str]
    handler: ToolCallable


class ToolRegistry:
    """Registry that deliberately has no arbitrary shell execution support."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool {definition.name!r} is already registered")
        self._tools[definition.name] = definition

    def names_for_role(self, role: str) -> list[str]:
        return [
            definition.name
            for definition in self._tools.values()
            if role in definition.allowed_roles
        ]

    def execute(
        self,
        *,
        tool_name: str,
        role: str,
        arguments: dict[str, Any],
    ) -> str:
        try:
            definition = self._tools[tool_name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool {tool_name!r} is not registered") from exc
        if role not in definition.allowed_roles:
            raise ToolPermissionError(
                f"Role {role!r} is not allowed to use tool {tool_name!r}"
            )
        try:
            output = definition.handler(arguments)
        except Exception as exc:
            logger.exception("Safe tool %s failed", tool_name)
            raise ToolError(f"Tool {tool_name!r} failed: {exc}") from exc
        if not output.strip():
            raise ToolError(f"Tool {tool_name!r} returned empty output")
        return output


def build_default_tool_registry() -> ToolRegistry:
    """Build the stage-two set of non-destructive simulated tools."""

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="analyze_incident",
            description="Analyze supplied evidence without changing external systems.",
            allowed_roles=frozenset({"executor"}),
            handler=lambda arguments: (
                "诊断分析完成："
                + str(arguments.get("evidence_summary", "未提供证据摘要"))
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="validate_recovery",
            description="Evaluate deterministic recovery criteria.",
            allowed_roles=frozenset({"executor"}),
            handler=lambda arguments: (
                "恢复检查项："
                + "；".join(
                    str(item) for item in arguments.get("criteria", [])
                )
            ),
        )
    )
    return registry
