"""Sequential text-only collaboration runtime."""

from pathlib import Path
from time import perf_counter

from app.agents import (
    ExecutorAgent,
    PlannerAgent,
    RetrieverAgent,
    ReviewerAgent,
)
from app.agents.base import AgentExecutionError, BaseAgent
from app.core.logging import get_logger
from app.models.domain import (
    AgentRole,
    Task,
    TaskCreate,
    TaskRecord,
    TaskResult,
    TaskStatus,
    TextMessage,
    utc_now,
)
from app.runtime.fake_llm import FakeLLM
from app.runtime.metrics import MetricsWriter
from app.runtime.store import TaskStore

logger = get_logger(__name__)


class OrchestrationError(RuntimeError):
    """Raised when the sequential collaboration cannot complete."""


class TextTaskOrchestrator:
    """Run the fixed Planner -> Retriever -> Executor -> Reviewer workflow."""

    def __init__(
        self,
        metrics_dir: Path,
        llm: FakeLLM | None = None,
        store: TaskStore | None = None,
    ) -> None:
        engine = llm or FakeLLM()
        self._agents: tuple[BaseAgent, ...] = (
            PlannerAgent(engine),
            RetrieverAgent(engine),
            ExecutorAgent(engine),
            ReviewerAgent(engine),
        )
        self._metrics = MetricsWriter(metrics_dir)
        self._store = store or TaskStore()

    async def run(self, task_create: TaskCreate) -> TaskResult:
        """Execute all four agents and persist the measured text baseline."""

        task = Task(
            title=task_create.title,
            prompt=task_create.prompt,
            status=TaskStatus.RUNNING,
        )
        await self._store.save(TaskRecord(task=task))
        messages: list[TextMessage] = []
        input_text = task.prompt
        started = perf_counter()

        try:
            for index, agent in enumerate(self._agents):
                output = await agent.run(task, input_text)
                receiver = (
                    self._agents[index + 1].profile.role
                    if index + 1 < len(self._agents)
                    else AgentRole.USER
                )
                message = TextMessage(
                    task_id=task.task_id,
                    sender=agent.profile.role,
                    receiver=receiver,
                    content=output,
                )
                messages.append(message)
                input_text = output

            elapsed_ms = (perf_counter() - started) * 1000
            metrics = self._metrics.save(task.task_id, elapsed_ms, messages)
            task.status = TaskStatus.COMPLETED
            task.updated_at = utc_now()
            result = TaskResult(
                task_id=task.task_id,
                final_answer=messages[-1].content,
                messages=messages,
                metrics=metrics,
            )
            await self._store.save(TaskRecord(task=task, result=result))
            logger.info("Task %s completed in %.3f ms", task.task_id, elapsed_ms)
            return result
        except (AgentExecutionError, RuntimeError, OSError) as exc:
            task.status = TaskStatus.FAILED
            task.updated_at = utc_now()
            await self._store.save(TaskRecord(task=task, error=str(exc)))
            logger.exception("Task %s failed", task.task_id)
            raise OrchestrationError(
                f"Task {task.task_id} failed: {exc}"
            ) from exc

    async def get_task(self, task_id: str) -> TaskRecord | None:
        """Return a previously submitted task record."""

        return await self._store.get(task_id)
