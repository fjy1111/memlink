"""Independent input and output contracts for the four MemLink agents."""

from typing import Any

from pydantic import BaseModel, Field, model_validator


class PlannerInput(BaseModel):
    """Information available to the planning role."""

    original_task: str
    task_topic: str
    available_agents: list[dict[str, Any]]
    available_tools: list[str]
    reusable_memory_summaries: list[str] = Field(default_factory=list)


class TaskPlan(BaseModel):
    """Validated decomposition produced by the Planner."""

    goal: str
    steps: list[str] = Field(min_length=1)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    assigned_capability: dict[str, str]
    risks: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_assignments(self) -> "TaskPlan":
        """Require every numbered plan step to have a capability assignment."""

        required = {str(index) for index in range(1, len(self.steps) + 1)}
        missing = required.difference(self.assigned_capability)
        if missing:
            raise ValueError(f"Missing capability assignments for steps {sorted(missing)}")
        return self


class RetrieverInput(BaseModel):
    """Plan and memory context available to the retrieval role."""

    task_plan: TaskPlan
    current_step: str
    task_topic: str
    query_text: str
    knowledge_items: list[str] = Field(default_factory=list)
    shared_memories: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """One evidence record with a stable identifier."""

    evidence_id: str
    content: str
    source_type: str
    relevance_score: float = Field(ge=0.0, le=1.0)


class EvidenceBundle(BaseModel):
    """Evidence selected by Retriever without forming the final answer."""

    query: str
    evidence_items: list[EvidenceItem] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    source_types: list[str] = Field(min_length=1)
    relevance_scores: list[float] = Field(min_length=1)
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_evidence_alignment(self) -> "EvidenceBundle":
        """Keep item identifiers and parallel summary fields consistent."""

        item_ids = [item.evidence_id for item in self.evidence_items]
        if item_ids != self.evidence_ids:
            raise ValueError("evidence_ids must match evidence_items order")
        if len(self.source_types) != len(self.evidence_items):
            raise ValueError("source_types length must match evidence_items")
        if len(self.relevance_scores) != len(self.evidence_items):
            raise ValueError("relevance_scores length must match evidence_items")
        return self


class ExecutorInput(BaseModel):
    """Plan, evidence, and safe actions available to Executor."""

    task_plan: TaskPlan
    evidence_bundle: EvidenceBundle
    allowed_actions: list[str] = Field(min_length=1)


class ExecutionResult(BaseModel):
    """Outcome of one allow-listed deterministic action."""

    action: str
    success: bool
    result_summary: str
    result_ref: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    retryable: bool = False


class ReviewerInput(BaseModel):
    """Complete evidence chain available only to Reviewer."""

    original_task: str
    task_plan: TaskPlan
    evidence_bundle: EvidenceBundle
    execution_result: ExecutionResult
    relevant_memories: list[dict[str, Any]] = Field(default_factory=list)


class ReviewResult(BaseModel):
    """Evidence-aware final decision produced by Reviewer."""

    passed: bool
    final_answer: str
    missing_evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    should_store_memory: bool = False
