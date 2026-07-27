"""Planner agent."""

from app.agents.base import BaseAgent
from app.models.domain import Agent, AgentRole


class PlannerAgent(BaseAgent):
    """Break an incident report into an ordered investigation plan."""

    @property
    def profile(self) -> Agent:
        return Agent(
            name="Planner Agent",
            role=AgentRole.PLANNER,
            description="Plans and decomposes enterprise incident analysis tasks.",
        )
