"""Reviewer agent."""

from app.agents.base import BaseAgent
from app.agents.contracts import ReviewerInput, ReviewResult
from app.models.domain import Agent, AgentRole, Task
from app.protocol import MessageAction


class ReviewerAgent(BaseAgent):
    """Review evidence coverage and produce the final answer."""

    system_prompt = (
        "You are Reviewer Agent. Check plan completion, evidence IDs, execution "
        "success, contradictions, and whether validated experience should be stored."
    )
    capabilities = ("evidence_review", "final_response", "memory_curation")
    accepted_actions = (
        MessageAction.HANDSHAKE,
        MessageAction.REVIEW_RESULT,
    )
    input_model_name = ReviewerInput.__name__
    output_model_name = ReviewResult.__name__
    allowed_tools = ()

    @property
    def profile(self) -> Agent:
        return Agent(
            name="Reviewer Agent",
            role=AgentRole.REVIEWER,
            description="Reviews conclusions and returns an evidence-aware answer.",
        )

    def build_text_prompt(self, task: Task, input_text: str) -> str:
        return (
            f"任务：{task.title}\n原始问题：{task.prompt}\n"
            f"收到的完整执行上下文：\n{input_text}\n"
            "核对证据与执行结果后，输出企业技术故障分析最终报告。"
        )

    async def review(self, reviewer_input: ReviewerInput) -> ReviewResult:
        """Validate the evidence chain before approving a final answer."""

        existing_ids = set(reviewer_input.evidence_bundle.evidence_ids)
        execution_ids = set(reviewer_input.execution_result.evidence_ids)
        invalid_ids = sorted(execution_ids.difference(existing_ids))
        completed_capabilities = {
            "knowledge_retrieval",
            "safe_execution",
            "evidence_review",
        }
        missing_capabilities = sorted(
            set(reviewer_input.task_plan.assigned_capability.values()).difference(
                completed_capabilities
            )
        )
        try:
            generated = await self._llm.generate(
                system_prompt=self.system_prompt,
                user_prompt=reviewer_input.model_dump_json(),
                response_model=ReviewResult,
                context={
                    "original_task": reviewer_input.original_task,
                    "execution_success": reviewer_input.execution_result.success,
                    "evidence_ids": reviewer_input.evidence_bundle.evidence_ids,
                },
            )
        except Exception as exc:
            from app.agents.base import AgentExecutionError

            raise AgentExecutionError(f"Reviewer failed: {exc}") from exc
        if not isinstance(generated, ReviewResult):
            raise TypeError("Reviewer must return ReviewResult")
        if invalid_ids:
            generated.passed = False
            generated.should_store_memory = False
            generated.missing_evidence.extend(invalid_ids)
            generated.confidence = min(generated.confidence, 0.4)
        if missing_capabilities:
            generated.passed = False
            generated.should_store_memory = False
            generated.missing_evidence.extend(
                f"未完成能力：{capability}"
                for capability in missing_capabilities
            )
            generated.confidence = min(generated.confidence, 0.4)
        if not reviewer_input.execution_result.success:
            generated.passed = False
            generated.should_store_memory = False
            generated.recommendations.append("执行失败，需要处理错误后重新审查")
        return generated
