"""Independent input and output contracts for the four MemLink agents."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlannerInput(BaseModel):
    """Information available to the planning role."""

    original_task: str
    task_topic: str
    available_agents: list[dict[str, Any]]
    available_tools: list[str]
    reusable_memory_summaries: list[str] = Field(default_factory=list)


class TaskPlan(BaseModel):
    """Validated decomposition produced by the Planner."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "goal": "定位并缓解 API 延迟故障",
                    "steps": [
                        "检索故障窗口内的指标和变更证据",
                        "基于证据执行安全诊断",
                        "审查证据覆盖和恢复标准",
                    ],
                    "dependencies": {"2": ["1"], "3": ["1", "2"]},
                    "assigned_capability": {
                        "1": "knowledge_retrieval",
                        "2": "safe_execution",
                        "3": "evidence_review",
                    },
                    "risks": ["证据不足可能导致误判"],
                    "success_criteria": ["结论关联有效 evidence_id"],
                }
            ]
        }
    )

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

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "query": "API 延迟升高",
                    "evidence_items": [
                        {
                            "evidence_id": "evidence-1",
                            "content": "发布后 P95 延迟从 200ms 升至 900ms",
                            "source_type": "knowledge",
                            "relevance_score": 0.95,
                        }
                    ],
                    "evidence_ids": ["evidence-1"],
                    "source_types": ["knowledge"],
                    "relevance_scores": [0.95],
                    "summary": "发布变更与延迟升高存在时间相关性",
                    "confidence": 0.9,
                }
            ]
        }
    )

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

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "action": "analyze_incident",
                    "success": True,
                    "result_summary": "建议执行可回滚的版本回退并观察 P95",
                    "result_ref": None,
                    "evidence_ids": ["evidence-1"],
                    "error_code": None,
                    "retryable": False,
                }
            ]
        }
    )

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

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "passed": True,
                    "final_answer": "回退最近版本并验证 P95 和错误率恢复。",
                    "missing_evidence": [],
                    "contradictions": [],
                    "recommendations": ["保留回退前后的监控对照"],
                    "confidence": 0.9,
                    "should_store_memory": True,
                }
            ]
        }
    )

    passed: bool
    final_answer: str
    missing_evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    should_store_memory: bool = False
