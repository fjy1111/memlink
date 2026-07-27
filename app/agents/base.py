"""Common interface used by every MemLink agent."""

from abc import ABC, abstractmethod
from typing import ClassVar

from app.core.logging import get_logger
from app.llm import LLMClient
from app.models.domain import Agent, Task
from app.protocol import AgentRegistration, MessageAction

logger = get_logger(__name__)


class AgentExecutionError(RuntimeError):
    """Raised when an agent cannot generate its output."""


class BaseAgent(ABC):
    """Uniform asynchronous interface for all stage-one agents."""

    system_prompt: ClassVar[str]
    capabilities: ClassVar[tuple[str, ...]]
    accepted_actions: ClassVar[tuple[MessageAction, ...]]
    input_model_name: ClassVar[str]
    output_model_name: ClassVar[str]
    allowed_tools: ClassVar[tuple[str, ...]] = ()

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    @property
    @abstractmethod
    def profile(self) -> Agent:
        """Return the role metadata for this agent."""

    @property
    def registration(self) -> AgentRegistration:
        """Return the structured capability contract used for routing."""

        return AgentRegistration(
            agent_id=self.profile.role.value,
            name=self.profile.name,
            role=self.profile.role.value,
            capabilities=list(self.capabilities),
            accepted_actions=list(self.accepted_actions),
            input_model=self.input_model_name,
            output_model=self.output_model_name,
            allowed_tools=list(self.allowed_tools),
        )

    async def run(self, task: Task, input_text: str) -> str:
        """Generate one complete natural-language handoff for text mode."""

        try:
            logger.info(
                "Agent %s started task %s",
                self.profile.role.value,
                task.task_id,
            )
            generated = await self._llm.generate(
                system_prompt=self.system_prompt,
                user_prompt=self.build_text_prompt(task, input_text),
                context={
                    "role": self.profile.role.value,
                    "task_title": task.title,
                    "task_prompt": task.prompt,
                },
            )
            if not isinstance(generated, str):
                raise AgentExecutionError(
                    f"{self.profile.name} returned structured output in text mode"
                )
            output = generated
            if not output.strip():
                raise AgentExecutionError(
                    f"{self.profile.name} produced an empty response"
                )
            logger.info(
                "Agent %s completed task %s",
                self.profile.role.value,
                task.task_id,
            )
            return output
        except AgentExecutionError:
            raise
        except Exception as exc:
            logger.exception(
                "Agent %s failed task %s",
                self.profile.role.value,
                task.task_id,
            )
            raise AgentExecutionError(
                f"{self.profile.name} failed: {exc}"
            ) from exc

    @abstractmethod
    def build_text_prompt(self, task: Task, input_text: str) -> str:
        """Build the role-specific text-mode prompt."""
