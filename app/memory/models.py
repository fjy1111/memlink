"""Cross-task shared-memory domain models."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.domain import utc_now


class MemoryType(StrEnum):
    """Supported long-lived memory categories."""

    FACT = "fact"
    EVIDENCE = "evidence"
    STRATEGY = "strategy"
    SUCCESS_EXPERIENCE = "success_experience"
    FAILURE_EXPERIENCE = "failure_experience"


class SharedMemory(BaseModel):
    """Reusable knowledge distinct from current context and message history."""

    memory_id: str = Field(default_factory=lambda: str(uuid4()))
    task_topic: str = Field(min_length=1)
    source_agent: str = Field(min_length=1)
    memory_type: MemoryType
    summary: str = Field(min_length=1)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    semantic_state_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    usage_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MemorySearchHit(BaseModel):
    """One retrieved memory and its query-specific score."""

    memory: SharedMemory
    score: float = Field(ge=0.0, le=1.0)
    match_type: str


class MemoryStoreStats(BaseModel):
    """Cumulative query and reuse counters."""

    query_count: int = 0
    query_hit_count: int = 0
    hit_count: int = 0
    reused_memory_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
