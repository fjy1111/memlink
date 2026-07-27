"""Common interface used by every MemLink agent."""

from abc import ABC, abstractmethod

from app.core.logging import get_logger
from app.models.domain import Agent, Task
from app.runtime.fake_llm import FakeLLM

logger = get_logger(__name__)


class AgentExecutionError(RuntimeError):
    """Raised when an agent cannot generate its output."""


class BaseAgent(ABC):
    """Uniform asynchronous interface for all stage-one agents."""

    def __init__(self, llm: FakeLLM) -> None:
        self._llm = llm

    @property
    @abstractmethod
    def profile(self) -> Agent:
        """Return the role metadata for this agent."""

    async def run(self, task: Task, input_text: str) -> str:
        """Generate one complete natural-language handoff."""

        try:
            logger.info(
                "Agent %s started task %s",
                self.profile.role.value,
                task.task_id,
            )
            output = await self._llm.generate(
                role=self.profile.role,
                task=task,
                input_text=input_text,
            )
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
