"""Validated configuration and result models for reproducible benchmarks."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from app.models import CommunicationMode, TaskStatus


class ExperimentName(StrEnum):
    """Stable identifiers used by the benchmark matrix and result files."""

    TEXT = "text"
    STRUCTURED = "structured"
    STRUCTURED_NO_MEMORY = "structured_no_memory"
    STRUCTURED_NO_SEMANTIC_STATE = "structured_no_semantic_state"
    STRUCTURED_NO_RESULT_REF = "structured_no_result_ref"


class ExperimentDefinition(BaseModel):
    """One real execution branch in the formal experiment matrix."""

    name: ExperimentName
    communication_mode: CommunicationMode
    enable_shared_memory: bool
    enable_semantic_state: bool
    enable_result_reference: bool


class BenchmarkConfig(BaseModel):
    """Inputs held constant across every selected experiment."""

    rounds: int = Field(default=10, ge=1, le=1000)
    seed: int = 2026
    results_dir: Path
    temporary_root: Path | None = None
    experiment: str = "all"


class BenchmarkRunRecord(BaseModel):
    """Raw, non-aggregated observation for one real task execution."""

    run_id: str
    experiment_name: ExperimentName
    communication_mode: CommunicationMode
    task_group: str
    task_id: str
    source_task_id: str
    round_index: int = Field(ge=1)
    success: bool
    task_status: TaskStatus
    message_count: int = Field(ge=0)
    protocol_message_count: int = Field(ge=0)
    text_character_count: int = Field(ge=0)
    estimated_token_count: int = Field(ge=0)
    json_serialized_bytes: int = Field(ge=0)
    msgpack_serialized_bytes: int = Field(ge=0)
    semantic_state_transfer_count: int = Field(ge=0)
    semantic_state_bytes: int = Field(ge=0)
    memory_query_count: int = Field(ge=0)
    memory_hit_count: int = Field(ge=0)
    memory_hit_rate: float = Field(ge=0.0, le=1.0)
    reused_memory_ids: list[str] = Field(default_factory=list)
    repeated_retrieval_count: int = Field(ge=0)
    result_reference_count: int = Field(ge=0)
    full_result_transfer_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    total_duration_ms: float = Field(ge=0.0)
    agent_execution_time: dict[str, float] = Field(default_factory=dict)
    sqlite_record_count_before: int = Field(ge=0)
    sqlite_record_count_after: int = Field(ge=0)
    semantic_state_file_count_before: int = Field(ge=0)
    semantic_state_file_count_after: int = Field(ge=0)
    timestamp: datetime
    python_version: str
    operating_system: str
    error_message: str | None = None


class DescriptiveStatistics(BaseModel):
    """Aggregate values for one numeric metric."""

    mean: float
    minimum: float
    maximum: float
    p50: float
    p95: float
    standard_deviation: float


class ExperimentSummary(BaseModel):
    """Truthful aggregate for one experiment definition."""

    experiment_name: ExperimentName
    communication_mode: CommunicationMode
    run_count: int = Field(ge=0)
    completion_rate: float = Field(ge=0.0, le=1.0)
    error_rate: float = Field(ge=0.0, le=1.0)
    average_memory_hit_rate: float = Field(ge=0.0, le=1.0)
    metrics: dict[str, DescriptiveStatistics]


class ExperimentResourceStatus(BaseModel):
    """Resource checks performed when one isolated experiment ends."""

    experiment_name: ExperimentName
    cleanup_success: bool
    database_handle_released: bool
    temporary_file_residue_count: int = Field(ge=0)
    background_process_count: int = Field(ge=0)


class StabilitySummary(BaseModel):
    """Continuous-run totals and cleanup checks for structured mode."""

    experiment_name: ExperimentName
    total_tasks: int = Field(ge=0)
    successful_tasks: int = Field(ge=0)
    failed_tasks: int = Field(ge=0)
    exception_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    total_duration_ms: float = Field(ge=0.0)
    p50_duration_ms: float = Field(ge=0.0)
    p95_duration_ms: float = Field(ge=0.0)
    sqlite_record_growth: int
    semantic_state_file_growth: int
    cleanup_success: bool
    database_handle_released: bool
    temporary_file_residue_count: int = Field(ge=0)
    background_process_count: int = Field(ge=0)


class BenchmarkArtifacts(BaseModel):
    """Paths and counts returned by a completed benchmark invocation."""

    records: list[BenchmarkRunRecord]
    summaries: list[ExperimentSummary]
    stability: StabilitySummary | None
    resource_statuses: list[ExperimentResourceStatus]
    output_files: dict[str, Path]

