"""Validated records produced by the two evidence-oriented experiments."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class StatisticValues(BaseModel):
    """Descriptive statistics kept in both JSON and flattened CSV summaries."""

    mean: float
    p50: float
    p95: float
    standard_deviation: float


class ContextScalingRecord(BaseModel):
    """One isolated context-scaling task execution."""

    experiment: str
    context_scale: str
    round: int = Field(ge=1)
    task_id: str
    success: bool
    elapsed_ms: float = Field(ge=0.0)
    message_count: int = Field(ge=0)
    text_characters: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    utf8_payload_bytes: int = Field(ge=0)
    json_bytes: int = Field(ge=0)
    msgpack_bytes: int = Field(ge=0)
    result_ref_count: int = Field(ge=0)
    result_ref_payload_bytes: int = Field(ge=0)
    inlined_payload_bytes: int = Field(ge=0)
    repeated_payload_bytes: int = Field(ge=0)
    repeated_payload_ratio: float = Field(ge=0.0)
    semantic_state_count: int = Field(ge=0)
    semantic_state_binary_bytes: int = Field(ge=0)
    state_reference_bytes: int = Field(ge=0)
    memory_hit_count: int = Field(ge=0)


class MemoryReuseRecord(BaseModel):
    """One isolated shared-memory target-task execution."""

    scenario: str
    condition: str
    round: int = Field(ge=1)
    task_id: str
    success: bool
    elapsed_ms: float = Field(ge=0.0)
    message_count: int = Field(ge=0)
    text_characters: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    json_bytes: int = Field(ge=0)
    msgpack_bytes: int = Field(ge=0)
    memory_query_count: int = Field(ge=0)
    memory_hit_count: int = Field(ge=0)
    retrieved_memory_ids: list[str] = Field(default_factory=list)
    reused_memory_ids: list[str] = Field(default_factory=list)
    expected_memory_ids: list[str] = Field(default_factory=list)
    irrelevant_memory_ids: list[str] = Field(default_factory=list)
    relevant_memory_reused: bool
    irrelevant_memory_reused: bool
    memory_reuse_precision: float = Field(ge=0.0, le=1.0)
    repeated_steps: int = Field(ge=0)
    avoided_steps: int = Field(ge=0)
    repeated_payload_bytes: int = Field(ge=0)
    reviewer_accepted: bool
    reviewer_rejected_memory: list[str] = Field(default_factory=list)
    final_confidence: float = Field(ge=0.0, le=1.0)


class EvidenceExperimentArtifacts(BaseModel):
    """Files, records, and cleanup checks returned by one experiment."""

    record_count: int = Field(ge=0)
    task_execution_count: int = Field(ge=0)
    output_files: dict[str, Path]
    figure_files: list[Path] = Field(default_factory=list)
    cleanup_success: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
