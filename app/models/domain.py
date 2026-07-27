"""Stage-one task, agent, text-message, and result models."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class TaskStatus(StrEnum):
    """Lifecycle of a task in the local runtime."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CommunicationMode(StrEnum):
    """Supported agent-to-agent communication formats."""

    TEXT = "text"
    STRUCTURED = "structured"


class LLMBackend(StrEnum):
    """Backends selectable by request without carrying credentials."""

    FAKE = "fake"
    OPENAI_COMPATIBLE = "openai_compatible"


class AgentRole(StrEnum):
    """The four stage-one collaboration roles plus the external caller."""

    USER = "user"
    PLANNER = "planner"
    RETRIEVER = "retriever"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"


class TaskCreate(BaseModel):
    """Input accepted by the task execution API."""

    title: str = Field(default="Enterprise incident analysis", min_length=1, max_length=120)
    prompt: str = Field(min_length=5, max_length=10_000)
    mode: CommunicationMode = CommunicationMode.TEXT
    llm_backend: LLMBackend | None = None
    task_topic: str | None = Field(default=None, min_length=1, max_length=120)


class Task(BaseModel):
    """Stored task state."""

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    prompt: str
    task_topic: str
    mode: CommunicationMode = CommunicationMode.TEXT
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Agent(BaseModel):
    """Public description shared by every concrete agent."""

    name: str
    role: AgentRole
    description: str


class TextMessage(BaseModel):
    """A complete natural-language message exchanged by two participants."""

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    sender: AgentRole
    receiver: AgentRole
    content: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)


class RunMetrics(BaseModel):
    """Comparable raw metrics for text and structured runs."""

    elapsed_ms: float = Field(ge=0)
    message_count: int = Field(ge=0)
    character_count: int = Field(ge=0)
    estimated_token_count: int = Field(ge=0)
    metrics_file: str
    communication_mode: CommunicationMode = CommunicationMode.TEXT
    protocol_message_count: int = Field(default=0, ge=0)
    text_character_count: int = Field(default=0, ge=0)
    json_serialized_bytes: int = Field(default=0, ge=0)
    msgpack_serialized_bytes: int = Field(default=0, ge=0)
    semantic_state_transfer_count: int = Field(default=0, ge=0)
    semantic_state_bytes: int = Field(default=0, ge=0)
    memory_query_count: int = Field(default=0, ge=0)
    memory_hit_count: int = Field(default=0, ge=0)
    memory_hit_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    reused_memory_ids: list[str] = Field(default_factory=list)
    repeated_retrieval_count: int = Field(default=0, ge=0)
    result_reference_count: int = Field(default=0, ge=0)
    full_result_transfer_count: int = Field(default=0, ge=0)
    agent_execution_time: dict[str, float] = Field(default_factory=dict)
    total_duration_ms: float = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    task_status: TaskStatus = TaskStatus.COMPLETED


class TaskResult(BaseModel):
    """Successful final result returned by the execution endpoint."""

    task_id: str
    communication_mode: CommunicationMode = CommunicationMode.TEXT
    final_answer: str
    messages: list[TextMessage | dict[str, Any]]
    protocol_messages: list[dict[str, Any]] = Field(default_factory=list)
    agent_trace: list[str] = Field(default_factory=list)
    memory_hit_count: int = 0
    reused_memory_ids: list[str] = Field(default_factory=list)
    review_passed: bool | None = None
    review_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    metrics: RunMetrics
    completed_at: datetime = Field(default_factory=utc_now)


class TaskRecord(BaseModel):
    """Task state and optional result returned by the lookup endpoint."""

    task: Task
    result: TaskResult | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """Health endpoint response."""

    status: Literal["ok"]
    service: str
    version: str
