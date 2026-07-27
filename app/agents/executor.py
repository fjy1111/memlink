"""Executor agent."""

from app.agents.base import BaseAgent
from app.models.domain import Agent, AgentRole


class ExecutorAgent(BaseAgent):
    """Turn retrieved material into concrete diagnostic actions."""

    @property
    def profile(self) -> Agent:
        return Agent(
            name="Executor Agent",
            role=AgentRole.EXECUTOR,
            description="Executes the analysis plan and produces a diagnosis.",
        )
