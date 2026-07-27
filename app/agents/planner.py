"""Planner agent."""

from app.agents.base import BaseAgent
from app.agents.contracts import PlannerInput, TaskPlan
from app.models.domain import Agent, AgentRole, Task
from app.protocol import MessageAction


class PlannerAgent(BaseAgent):
    """Break an incident report into an ordered investigation plan."""

    system_prompt = (
        "You are Planner Agent. Decompose goals and dependencies only. "
        "Never execute tools or claim that an action has already run."
    )
    capabilities = ("task_planning", "risk_analysis")
    accepted_actions = (MessageAction.HANDSHAKE, MessageAction.PLAN_TASK)
    input_model_name = PlannerInput.__name__
    output_model_name = TaskPlan.__name__
    allowed_tools = ()

    @property
    def profile(self) -> Agent:
        return Agent(
            name="Planner Agent",
            role=AgentRole.PLANNER,
            description="Plans and decomposes enterprise incident analysis tasks.",
        )

    def build_text_prompt(self, task: Task, input_text: str) -> str:
        return (
            f"任务：{task.title}\n原始问题：{task.prompt}\n"
            f"当前完整上下文：\n{input_text}\n"
            "仅输出排查步骤、依赖、风险和成功标准。"
        )

    async def plan(self, planner_input: PlannerInput) -> TaskPlan:
        """Produce a validated plan without invoking any tools."""

        try:
            generated = await self._llm.generate(
                system_prompt=self.system_prompt,
                user_prompt=planner_input.model_dump_json(),
                response_model=TaskPlan,
                context={
                    "original_task": planner_input.original_task,
                    "memory_summaries": planner_input.reusable_memory_summaries,
                },
            )
        except Exception as exc:
            from app.agents.base import AgentExecutionError

            raise AgentExecutionError(f"Planner failed: {exc}") from exc
        if not isinstance(generated, TaskPlan):
            raise TypeError("Planner must return TaskPlan")
        return generated
