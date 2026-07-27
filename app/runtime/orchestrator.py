"""Dual-mode multi-agent orchestration with state and shared memory."""

import re
from pathlib import Path
from time import perf_counter
from typing import Any, Awaitable, TypeVar

from app.agents import (
    EvidenceBundle,
    ExecutorAgent,
    ExecutionResult,
    PlannerAgent,
    PlannerInput,
    RetrieverAgent,
    RetrieverInput,
    ReviewResult,
    ReviewerAgent,
    ReviewerInput,
    TaskPlan,
)
from app.agents.base import AgentExecutionError, BaseAgent
from app.agents.contracts import ExecutorInput
from app.core.config import Settings
from app.core.logging import get_logger
from app.llm import (
    EmbeddingClient,
    FakeEmbeddingClient,
    FakeLLMClient,
    LLMClient,
    create_embedding_client,
    create_llm_client,
)
from app.memory import (
    MemorySearchHit,
    MemoryType,
    SQLiteSharedMemoryStore,
    SharedMemory,
)
from app.models.domain import (
    AgentRole,
    CommunicationMode,
    Task,
    TaskCreate,
    TaskRecord,
    TaskResult,
    TaskStatus,
    TextMessage,
    utc_now,
)
from app.protocol import (
    AgentMessage,
    AgentRegistry,
    MessageAction,
    MessageStatus,
    ProtocolTrace,
)
from app.runtime.metrics import MetricsWriter
from app.runtime.store import TaskStore
from app.runtime.tools import ToolRegistry, build_default_tool_registry
from app.state import SemanticState, StateStore

logger = get_logger(__name__)
ResultT = TypeVar("ResultT")

BUILT_IN_INCIDENT_KNOWLEDGE = [
    "使用请求量、错误率、P95 延迟和资源饱和度四个黄金信号。",
    "检查最近发布、配置变更、依赖超时和数据库连接池等待。",
    "使用 trace_id 串联入口、业务逻辑、缓存、数据库和下游服务。",
    "限流、扩容或回退必须可逆，并保留前后监控对照。",
]


class OrchestrationError(RuntimeError):
    """Raised when a task cannot truthfully complete."""


class TaskOrchestrator:
    """Coordinate four distinct agents in text or structured mode."""

    def __init__(
        self,
        metrics_dir: Path,
        *,
        state_dir: Path | None = None,
        memory_db_path: Path | None = None,
        llm: LLMClient | None = None,
        embedding: EmbeddingClient | None = None,
        store: TaskStore | None = None,
        tool_registry: ToolRegistry | None = None,
        backend_name: str = "fake",
        enable_shared_memory: bool = True,
        enable_semantic_state: bool = True,
        enable_result_reference: bool = True,
    ) -> None:
        data_root = metrics_dir.parent
        self._llm = llm or FakeLLMClient()
        self._embedding = embedding or FakeEmbeddingClient()
        self._backend_name = backend_name
        self.enable_shared_memory = enable_shared_memory
        self.enable_semantic_state = enable_semantic_state
        self.enable_result_reference = enable_result_reference
        self._tool_registry = tool_registry or build_default_tool_registry()
        self._planner = PlannerAgent(self._llm)
        self._retriever = RetrieverAgent(self._llm)
        self._executor = ExecutorAgent(self._llm, self._tool_registry)
        self._reviewer = ReviewerAgent(self._llm)
        self._agents: tuple[BaseAgent, ...] = (
            self._planner,
            self._retriever,
            self._executor,
            self._reviewer,
        )
        self._agent_by_id = {
            agent.registration.agent_id: agent for agent in self._agents
        }
        self.registry = AgentRegistry()
        for agent in self._agents:
            self.registry.register(agent.registration)

        self.state_store = StateStore(state_dir or data_root / "states")
        self.memory_store = SQLiteSharedMemoryStore(
            memory_db_path or data_root / "memory" / "memlink.db"
        )
        self._metrics = MetricsWriter(metrics_dir)
        self._store = store or TaskStore()
        self._result_refs: dict[str, Any] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> "TaskOrchestrator":
        """Build every configured adapter without exposing credentials."""

        return cls(
            metrics_dir=settings.metrics_dir,
            state_dir=settings.state_dir,
            memory_db_path=settings.memory_db_path,
            llm=create_llm_client(settings),
            embedding=create_embedding_client(settings),
            backend_name=settings.llm_backend,
            enable_shared_memory=settings.enable_shared_memory,
            enable_semantic_state=settings.enable_semantic_state,
            enable_result_reference=settings.enable_result_reference,
        )

    async def run(self, task_create: TaskCreate) -> TaskResult:
        """Execute a task and persist state, memory, trace, and metrics."""

        requested_backend = (
            task_create.llm_backend.value if task_create.llm_backend else None
        )
        if requested_backend and requested_backend != self._backend_name:
            raise OrchestrationError(
                f"Request selected backend {requested_backend!r}, but application "
                f"is configured for {self._backend_name!r}"
            )
        task = Task(
            title=task_create.title,
            prompt=task_create.prompt,
            task_topic=task_create.task_topic or task_create.title,
            mode=task_create.mode,
            status=TaskStatus.RUNNING,
        )
        await self._store.save(TaskRecord(task=task))
        started = perf_counter()
        state_before = self.state_store.stats
        memory_before = self.memory_store.stats
        retry_before = self._retry_count()
        agent_times: dict[str, float] = {}

        try:
            (
                memories,
                query_state,
                repeated_retrieval_count,
            ) = await self._retrieve_reusable_memories(
                task,
                use_semantic=(
                    task.mode is CommunicationMode.STRUCTURED
                    and self.enable_semantic_state
                ),
            )
            if task.mode is CommunicationMode.TEXT:
                (
                    final_answer,
                    text_messages,
                    protocol_trace,
                    agent_trace,
                    review_result,
                    evidence_bundle,
                ) = await self._run_text(task, memories, agent_times)
            else:
                (
                    final_answer,
                    text_messages,
                    protocol_trace,
                    agent_trace,
                    review_result,
                    evidence_bundle,
                ) = await self._run_structured(
                    task,
                    memories,
                    query_state,
                    agent_times,
                )

            if self.enable_shared_memory and (
                review_result is None or review_result.should_store_memory
            ):
                await self._store_validated_memory(
                    task=task,
                    final_answer=final_answer,
                    evidence_ids=(
                        evidence_bundle.evidence_ids if evidence_bundle else []
                    ),
                    confidence=(
                        review_result.confidence if review_result else 0.8
                    ),
                )

            elapsed_ms = (perf_counter() - started) * 1000
            task.status = TaskStatus.COMPLETED
            task.updated_at = utc_now()
            state_after = self.state_store.stats
            memory_after = self.memory_store.stats
            reused_ids = [memory.memory_id for memory in memories]
            metrics = self._metrics.save(
                task.task_id,
                elapsed_ms,
                text_messages,
                mode=task.mode,
                protocol_trace=protocol_trace,
                semantic_state_transfer_count=(
                    state_after.transfer_count - state_before.transfer_count
                ),
                semantic_state_bytes=(
                    state_after.transferred_bytes - state_before.transferred_bytes
                ),
                memory_query_count=(
                    memory_after.query_count - memory_before.query_count
                ),
                memory_hit_count=(
                    memory_after.hit_count - memory_before.hit_count
                ),
                memory_query_hit_count=(
                    memory_after.query_hit_count
                    - memory_before.query_hit_count
                ),
                reused_memory_ids=reused_ids,
                repeated_retrieval_count=repeated_retrieval_count,
                agent_execution_time=agent_times,
                retry_count=self._retry_count() - retry_before,
                error_count=0,
                task_status=TaskStatus.COMPLETED,
            )
            protocol_messages = [
                message.model_dump(mode="json")
                for message in protocol_trace.messages
            ]
            result_messages: list[TextMessage | dict[str, Any]]
            if task.mode is CommunicationMode.TEXT:
                result_messages = list(text_messages)
            else:
                result_messages = list(protocol_messages)
            result = TaskResult(
                task_id=task.task_id,
                communication_mode=task.mode,
                final_answer=final_answer,
                messages=result_messages,
                protocol_messages=protocol_messages,
                agent_trace=agent_trace,
                memory_hit_count=metrics.memory_hit_count,
                reused_memory_ids=reused_ids,
                review_passed=(
                    review_result.passed
                    if review_result is not None
                    else None
                ),
                review_confidence=(
                    review_result.confidence
                    if review_result is not None
                    else None
                ),
                evidence_ids=(
                    evidence_bundle.evidence_ids
                    if evidence_bundle is not None
                    else []
                ),
                contradictions=(
                    review_result.contradictions
                    if review_result is not None
                    else []
                ),
                missing_evidence=(
                    review_result.missing_evidence
                    if review_result is not None
                    else []
                ),
                recommendations=(
                    review_result.recommendations
                    if review_result is not None
                    else []
                ),
                metrics=metrics,
            )
            await self._store.save(TaskRecord(task=task, result=result))
            logger.info(
                "Task %s completed in %s mode in %.3f ms",
                task.task_id,
                task.mode.value,
                elapsed_ms,
            )
            return result
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.updated_at = utc_now()
            await self._store.save(TaskRecord(task=task, error=str(exc)))
            logger.exception("Task %s failed", task.task_id)
            if isinstance(exc, OrchestrationError):
                raise
            raise OrchestrationError(
                f"Task {task.task_id} failed: {exc}"
            ) from exc

    async def get_task(self, task_id: str) -> TaskRecord | None:
        """Return a previously submitted task record."""

        return await self._store.get(task_id)

    async def _run_text(
        self,
        task: Task,
        memories: list[SharedMemory],
        agent_times: dict[str, float],
    ) -> tuple[
        str,
        list[TextMessage],
        ProtocolTrace,
        list[str],
        None,
        None,
    ]:
        """Preserve the stage-one complete natural-language handoff."""

        messages: list[TextMessage] = []
        memory_context = "\n".join(
            f"- [{memory.memory_id}] {memory.summary}" for memory in memories
        )
        input_text = task.prompt
        if memory_context:
            input_text += f"\n\n可复用共享记忆：\n{memory_context}"
        for index, agent in enumerate(self._agents):
            output = await self._timed_agent_call(
                agent.profile.role.value,
                agent.run(task, input_text),
                agent_times,
            )
            receiver = (
                self._agents[index + 1].profile.role
                if index + 1 < len(self._agents)
                else AgentRole.USER
            )
            messages.append(
                TextMessage(
                    task_id=task.task_id,
                    sender=agent.profile.role,
                    receiver=receiver,
                    content=output,
                )
            )
            input_text = output
        return (
            messages[-1].content,
            messages,
            ProtocolTrace(),
            [agent.profile.role.value for agent in self._agents],
            None,
            None,
        )

    async def _run_structured(
        self,
        task: Task,
        memories: list[SharedMemory],
        query_state: SemanticState | None,
        agent_times: dict[str, float],
    ) -> tuple[
        str,
        list[TextMessage],
        ProtocolTrace,
        list[str],
        ReviewResult,
        EvidenceBundle,
    ]:
        """Route compact structured messages by discovered capabilities."""

        trace = ProtocolTrace()
        for message in self.registry.build_handshake_messages(task.task_id):
            self.registry.validate_message(message)
            trace.append(message)

        planner_registration = self.registry.require_capability(
            "task_planning",
            MessageAction.PLAN_TASK,
        )
        plan_request = AgentMessage(
            task_id=task.task_id,
            correlation_id=task.task_id,
            sender="orchestrator",
            receiver=planner_registration.agent_id,
            action=MessageAction.PLAN_TASK,
            parameters={
                "task_topic": task.task_topic,
                "original_task": task.prompt,
                "reused_memory_ids": [memory.memory_id for memory in memories],
            },
            capability_required=["task_planning"],
            semantic_state_ids=[query_state.state_id] if query_state else [],
            status=MessageStatus.ACCEPTED,
        )
        self._deliver(trace, plan_request)
        planner_input = PlannerInput(
            original_task=task.prompt,
            task_topic=task.task_topic,
            available_agents=[
                registration.model_dump(mode="json")
                for registration in self.registry.all()
            ],
            available_tools=self._tool_registry.names_for_role("executor"),
            reusable_memory_summaries=[memory.summary for memory in memories],
        )
        task_plan = await self._timed_agent_call(
            "planner",
            self._planner.plan(planner_input),
            agent_times,
        )
        plan_ref = self._maybe_put_result(
            task.task_id,
            "plan",
            task_plan,
        )
        plan_transfer = self._transfer_result(
            reference_key="plan_ref",
            value_key="task_plan",
            reference=plan_ref,
            value=task_plan,
        )

        retriever_registration = self.registry.require_capability(
            "knowledge_retrieval",
            MessageAction.RETRIEVE_EVIDENCE,
        )
        retrieve_request = AgentMessage(
            task_id=task.task_id,
            parent_message_id=plan_request.message_id,
            correlation_id=task.task_id,
            sender=planner_registration.agent_id,
            receiver=retriever_registration.agent_id,
            action=MessageAction.RETRIEVE_EVIDENCE,
            parameters={
                **plan_transfer,
                "current_step": "1",
                "task_topic": task.task_topic,
                "reused_memory_ids": [memory.memory_id for memory in memories],
            },
            result_ref=plan_ref,
            capability_required=["knowledge_retrieval"],
            semantic_state_ids=[query_state.state_id] if query_state else [],
            status=MessageStatus.ACCEPTED,
        )
        self._deliver(trace, retrieve_request)
        evidence_bundle = await self._timed_agent_call(
            "retriever",
            self._retriever.retrieve(
                RetrieverInput(
                    task_plan=task_plan,
                    current_step=task_plan.steps[0],
                    task_topic=task.task_topic,
                    query_text=task.prompt,
                    knowledge_items=BUILT_IN_INCIDENT_KNOWLEDGE,
                    shared_memories=[
                        memory.model_dump(mode="json") for memory in memories
                    ],
                )
            ),
            agent_times,
        )
        evidence_ref = self._maybe_put_result(
            task.task_id,
            "evidence",
            evidence_bundle,
        )
        evidence_transfer = self._transfer_result(
            reference_key="evidence_ref",
            value_key="evidence_bundle",
            reference=evidence_ref,
            value=evidence_bundle,
        )

        executor_registration = self.registry.require_capability(
            "safe_execution",
            MessageAction.EXECUTE_ACTION,
        )
        execute_request = AgentMessage(
            task_id=task.task_id,
            parent_message_id=retrieve_request.message_id,
            correlation_id=task.task_id,
            sender=retriever_registration.agent_id,
            receiver=executor_registration.agent_id,
            action=MessageAction.EXECUTE_ACTION,
            parameters={
                **plan_transfer,
                **evidence_transfer,
                "allowed_actions": ["analyze_incident"],
            },
            result_ref=evidence_ref,
            capability_required=["safe_execution"],
            confidence=evidence_bundle.confidence,
            evidence_ids=evidence_bundle.evidence_ids,
            semantic_state_ids=[query_state.state_id] if query_state else [],
            status=MessageStatus.ACCEPTED,
        )
        self._deliver(trace, execute_request)
        execution_result = await self._timed_agent_call(
            "executor",
            self._executor.execute(
                ExecutorInput(
                    task_plan=task_plan,
                    evidence_bundle=evidence_bundle,
                    allowed_actions=["analyze_incident"],
                )
            ),
            agent_times,
        )
        execution_ref = self._maybe_put_result(
            task.task_id,
            "execution",
            execution_result,
        )
        execution_transfer = self._transfer_result(
            reference_key="execution_ref",
            value_key="execution_result",
            reference=execution_ref,
            value=execution_result,
        )

        reviewer_registration = self.registry.require_capability(
            "evidence_review",
            MessageAction.REVIEW_RESULT,
        )
        review_request = AgentMessage(
            task_id=task.task_id,
            parent_message_id=execute_request.message_id,
            correlation_id=task.task_id,
            sender=executor_registration.agent_id,
            receiver=reviewer_registration.agent_id,
            action=MessageAction.REVIEW_RESULT,
            parameters={
                **plan_transfer,
                **evidence_transfer,
                **execution_transfer,
                "reused_memory_ids": [memory.memory_id for memory in memories],
            },
            result_ref=execution_ref,
            capability_required=["evidence_review"],
            confidence=evidence_bundle.confidence,
            evidence_ids=execution_result.evidence_ids,
            status=MessageStatus.ACCEPTED,
        )
        self._deliver(trace, review_request)
        review_result = await self._timed_agent_call(
            "reviewer",
            self._reviewer.review(
                ReviewerInput(
                    original_task=task.prompt,
                    task_plan=task_plan,
                    evidence_bundle=evidence_bundle,
                    execution_result=execution_result,
                    relevant_memories=[
                        memory.model_dump(mode="json") for memory in memories
                    ],
                )
            ),
            agent_times,
        )
        review_ref = self._maybe_put_result(
            task.task_id,
            "review",
            review_result,
        )
        review_transfer = self._transfer_result(
            reference_key="review_ref",
            value_key="review_result",
            reference=review_ref,
            value=review_result,
        )
        complete_message = AgentMessage(
            task_id=task.task_id,
            parent_message_id=review_request.message_id,
            correlation_id=task.task_id,
            sender=reviewer_registration.agent_id,
            receiver="orchestrator",
            action=MessageAction.TASK_COMPLETE,
            parameters={
                **review_transfer,
                "passed": review_result.passed,
            },
            result_ref=review_ref,
            confidence=review_result.confidence,
            evidence_ids=evidence_bundle.evidence_ids,
            status=(
                MessageStatus.COMPLETED
                if review_result.passed
                else MessageStatus.FAILED
            ),
        )
        trace.append(complete_message)
        if not review_result.passed:
            raise OrchestrationError(
                "Reviewer rejected the result: "
                + ", ".join(review_result.missing_evidence)
            )
        return (
            review_result.final_answer,
            [],
            trace,
            ["planner", "retriever", "executor", "reviewer"],
            review_result,
            evidence_bundle,
        )

    async def _retrieve_reusable_memories(
        self,
        task: Task,
        *,
        use_semantic: bool,
    ) -> tuple[list[SharedMemory], SemanticState | None, int]:
        """Retrieve actual persisted memories before planning."""

        hits: list[MemorySearchHit] = []
        if self.enable_shared_memory:
            hits.extend(
                self.memory_store.search_keyword(task.task_topic, limit=5)
            )
            hits.extend(
                self.memory_store.search_tags(
                    self._derive_tags(task.task_topic, task.prompt),
                    limit=5,
                )
            )
        query_state: SemanticState | None = None
        if use_semantic:
            query_vector = await self._embedding.embed(
                f"{task.task_topic}\n{task.prompt}"
            )
            query_state = self.state_store.save(
                task_id=task.task_id,
                source_agent="retriever",
                semantic_type="query_embedding",
                vector=query_vector,
                metadata={"purpose": "shared_memory_retrieval"},
            )
            loaded_query = self.state_store.load(query_state.state_id)
            if self.enable_shared_memory:
                hits.extend(
                    self.memory_store.search_vector(
                        loaded_query,
                        self.state_store,
                        limit=5,
                        minimum_similarity=-1.0,
                    )
                )
        unique: dict[str, SharedMemory] = {}
        for hit in hits:
            unique.setdefault(hit.memory.memory_id, hit.memory)
        repeated_retrieval_count = max(0, len(hits) - len(unique))
        return list(unique.values()), query_state, repeated_retrieval_count

    async def _store_validated_memory(
        self,
        *,
        task: Task,
        final_answer: str,
        evidence_ids: list[str],
        confidence: float,
    ) -> SharedMemory:
        """Persist only a completed task's reusable strategy."""

        semantic_state_id: str | None = None
        if self.enable_semantic_state:
            vector = await self._embedding.embed(
                f"{task.task_topic}\n{task.prompt}\n{final_answer}"
            )
            state = self.state_store.save(
                task_id=task.task_id,
                source_agent="reviewer",
                semantic_type="memory_embedding",
                vector=vector,
                metadata={"task_topic": task.task_topic},
            )
            semantic_state_id = state.state_id
        memory = SharedMemory(
            task_topic=task.task_topic,
            source_agent="reviewer",
            memory_type=MemoryType.SUCCESS_EXPERIENCE,
            summary=f"{task.title}：已验证的排查与止损策略",
            content=f"原始任务：{task.prompt}\n最终结论：{final_answer}",
            tags=self._derive_tags(task.task_topic, task.prompt),
            evidence_ids=evidence_ids,
            semantic_state_id=semantic_state_id,
            confidence=confidence,
        )
        return self.memory_store.add(memory)

    def _deliver(self, trace: ProtocolTrace, message: AgentMessage) -> None:
        """Validate a routed message, record state transfer, and append it."""

        self.registry.validate_message(message)
        for state_id in message.semantic_state_ids:
            self.state_store.record_transfer(state_id)
        trace.append(message)

    def _maybe_put_result(
        self,
        task_id: str,
        kind: str,
        value: Any,
    ) -> str | None:
        """Store a large result only when reference transfer is enabled."""

        if not self.enable_result_reference:
            return None
        reference = f"result:{task_id}:{kind}"
        self._result_refs[reference] = value
        return reference

    @staticmethod
    def _as_protocol_value(value: Any) -> Any:
        """Convert Pydantic results to JSON-compatible protocol values."""

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return model_dump(mode="json")
        return value

    def _transfer_result(
        self,
        *,
        reference_key: str,
        value_key: str,
        reference: str | None,
        value: Any,
    ) -> dict[str, Any]:
        """Transfer either one compact reference or the complete result."""

        if self.enable_result_reference:
            if reference is None:
                raise OrchestrationError("Result reference was not created")
            return {reference_key: reference}
        return {value_key: self._as_protocol_value(value)}

    def _retry_count(self) -> int:
        """Return cumulative retries exposed by configured adapters."""

        return int(getattr(self._llm, "retry_count", 0)) + int(
            getattr(self._embedding, "retry_count", 0)
        )

    @staticmethod
    def _derive_tags(task_topic: str, text: str) -> list[str]:
        tokens = {
            token.strip().lower()
            for token in re.split(r"[\s,，。:：/]+", f"{task_topic} {text}")
            if len(token.strip()) >= 2
        }
        tokens.add(task_topic.strip().lower())
        return sorted(tokens)[:12]

    @staticmethod
    async def _timed_agent_call(
        role: str,
        awaitable: Awaitable[ResultT],
        timings: dict[str, float],
    ) -> ResultT:
        started = perf_counter()
        try:
            return await awaitable
        except AgentExecutionError:
            raise
        finally:
            timings[role] = timings.get(role, 0.0) + (
                perf_counter() - started
            ) * 1000


TextTaskOrchestrator = TaskOrchestrator
