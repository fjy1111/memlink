"""Reviewer agent."""

from app.agents.base import BaseAgent
from app.models.domain import Agent, AgentRole


class ReviewerAgent(BaseAgent):
    """Review evidence coverage and produce the final answer."""

    @property
    def profile(self) -> Agent:
        return Agent(
            name="Reviewer Agent",
            role=AgentRole.REVIEWER,
            description="Reviews conclusions and returns an evidence-aware answer.",
        )
