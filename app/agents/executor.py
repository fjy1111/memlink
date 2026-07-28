"""Executor agent."""

from app.agents.base import BaseAgent
from app.agents.contracts import ExecutorInput, ExecutionResult
from app.llm import LLMClient
from app.models.domain import Agent, AgentRole, Task
from app.protocol import MessageAction
from app.runtime.tools import ToolError, ToolRegistry


class ExecutorAgent(BaseAgent):
    """Turn retrieved material into concrete diagnostic actions."""

    system_prompt = (
        "You are Executor Agent. Execute only allow-listed deterministic tools. "
        "Never invoke a shell or any unregistered action."
    )
    structured_system_prompt = (
        system_prompt
        + " In structured mode, output only the json object defined by the "
        "appended ExecutionResult Schema and complete example; never output "
        "Markdown or explanatory text."
    )
    capabilities = ("safe_execution", "incident_analysis")
    accepted_actions = (
        MessageAction.HANDSHAKE,
        MessageAction.EXECUTE_ACTION,
    )
    input_model_name = ExecutorInput.__name__
    output_model_name = ExecutionResult.__name__
    allowed_tools = ("analyze_incident", "validate_recovery")

    def __init__(self, llm: LLMClient, tool_registry: ToolRegistry) -> None:
        super().__init__(llm)
        self._tool_registry = tool_registry

    @property
    def profile(self) -> Agent:
        return Agent(
            name="Executor Agent",
            role=AgentRole.EXECUTOR,
            description="Executes the analysis plan and produces a diagnosis.",
        )

    def build_text_prompt(self, task: Task, input_text: str) -> str:
        return (
            f"任务：{task.title}\n原始问题：{task.prompt}\n"
            f"收到的完整证据上下文：\n{input_text}\n"
            "只提出并模拟执行安全、确定、可回滚的诊断动作。"
        )

    async def execute(self, executor_input: ExecutorInput) -> ExecutionResult:
        """Invoke one explicitly allowed tool and return a validated result."""

        action = executor_input.allowed_actions[0]
        if action not in self.allowed_tools:
            return ExecutionResult(
                action=action,
                success=False,
                result_summary="请求的动作不在 Executor 允许列表中。",
                evidence_ids=executor_input.evidence_bundle.evidence_ids,
                error_code="action_not_allowed",
                retryable=False,
            )
        try:
            tool_output = self._tool_registry.execute(
                tool_name=action,
                role=self.profile.role.value,
                arguments={
                    "evidence_summary": executor_input.evidence_bundle.summary,
                    "criteria": executor_input.task_plan.success_criteria,
                },
            )
        except ToolError as exc:
            return ExecutionResult(
                action=action,
                success=False,
                result_summary=str(exc),
                evidence_ids=executor_input.evidence_bundle.evidence_ids,
                error_code="tool_execution_failed",
                retryable=False,
            )
        try:
            generated = await self._llm.generate(
                system_prompt=self.structured_system_prompt,
                user_prompt=executor_input.model_dump_json(),
                response_model=ExecutionResult,
                context={
                    "role": "executor",
                    "action": action,
                    "evidence_ids": executor_input.evidence_bundle.evidence_ids,
                    "result_ref": f"tool:{action}",
                },
            )
        except Exception as exc:
            from app.agents.base import AgentExecutionError

            raise AgentExecutionError(f"Executor failed: {exc}") from exc
        if not isinstance(generated, ExecutionResult):
            raise TypeError("Executor must return ExecutionResult")
        generated.result_summary = tool_output
        return generated
