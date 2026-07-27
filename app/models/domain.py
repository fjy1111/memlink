"""Stage-one task, agent, text-message, and result models."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
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


class Task(BaseModel):
    """Stored task state."""

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    prompt: str
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
    """Measured communication and latency baseline for one run."""

    elapsed_ms: float = Field(ge=0)
    message_count: int = Field(ge=0)
    character_count: int = Field(ge=0)
    estimated_token_count: int = Field(ge=0)
    metrics_file: str


class TaskResult(BaseModel):
    """Successful final result returned by the execution endpoint."""

    task_id: str
    communication_mode: Literal["text"] = "text"
    final_answer: str
    messages: list[TextMessage]
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
