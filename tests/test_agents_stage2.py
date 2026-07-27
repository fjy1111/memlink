"""Tests proving that the four agents have distinct contracts and permissions."""

import pytest

from app.agents import (
    EvidenceBundle,
    ExecutorAgent,
    ExecutionResult,
    PlannerAgent,
    RetrieverAgent,
    ReviewerInput,
    ReviewerAgent,
    TaskPlan,
)
from app.agents.contracts import EvidenceItem
from app.llm import FakeLLMClient
from app.protocol import MessageAction
from app.runtime.tools import (
    ToolPermissionError,
    build_default_tool_registry,
)


def test_four_agents_advertise_distinct_contracts() -> None:
    llm = FakeLLMClient()
    tools = build_default_tool_registry()
    agents = [
        PlannerAgent(llm),
        RetrieverAgent(llm),
        ExecutorAgent(llm, tools),
        ReviewerAgent(llm),
    ]

    registrations = [agent.registration for agent in agents]

    assert len({registration.input_model for registration in registrations}) == 4
    assert len({registration.output_model for registration in registrations}) == 4
    assert len({agent.system_prompt for agent in agents}) == 4
    assert agents[0].registration.allowed_tools == []
    assert "vector_memory_search" in agents[1].registration.allowed_tools
    assert "analyze_incident" in agents[2].registration.allowed_tools
    assert agents[3].registration.allowed_tools == []
    assert MessageAction.PLAN_TASK in agents[0].registration.accepted_actions
    assert (
        MessageAction.RETRIEVE_EVIDENCE
        in agents[1].registration.accepted_actions
    )
    assert (
        MessageAction.EXECUTE_ACTION
        in agents[2].registration.accepted_actions
    )
    assert MessageAction.REVIEW_RESULT in agents[3].registration.accepted_actions


def test_tool_registry_rejects_non_executor_role() -> None:
    tools = build_default_tool_registry()

    with pytest.raises(ToolPermissionError):
        tools.execute(
            tool_name="analyze_incident",
            role="planner",
            arguments={"evidence_summary": "evidence"},
        )


def test_output_models_enforce_agent_specific_validation() -> None:
    plan = TaskPlan(
        goal="diagnose",
        steps=["retrieve"],
        assigned_capability={"1": "knowledge_retrieval"},
        success_criteria=["evidence exists"],
    )
    assert plan.steps == ["retrieve"]
    assert EvidenceBundle.model_fields["evidence_ids"].is_required()
    assert ExecutionResult.model_fields["success"].is_required()


@pytest.mark.asyncio
async def test_reviewer_rejects_unknown_evidence_and_unfinished_capability() -> None:
    reviewer = ReviewerAgent(FakeLLMClient())
    plan = TaskPlan(
        goal="diagnose",
        steps=["run unsupported step"],
        assigned_capability={"1": "unsupported_capability"},
        success_criteria=["verified"],
    )
    evidence = EvidenceBundle(
        query="query",
        evidence_items=[
            EvidenceItem(
                evidence_id="known-evidence",
                content="known",
                source_type="knowledge",
                relevance_score=0.9,
            )
        ],
        evidence_ids=["known-evidence"],
        source_types=["knowledge"],
        relevance_scores=[0.9],
        summary="known",
        confidence=0.9,
    )
    execution = ExecutionResult(
        action="analyze_incident",
        success=True,
        result_summary="done",
        evidence_ids=["unknown-evidence"],
    )

    review = await reviewer.review(
        ReviewerInput(
            original_task="diagnose",
            task_plan=plan,
            evidence_bundle=evidence,
            execution_result=execution,
        )
    )

    assert review.passed is False
    assert review.should_store_memory is False
    assert "unknown-evidence" in review.missing_evidence
    assert any(
        "unsupported_capability" in item for item in review.missing_evidence
    )
