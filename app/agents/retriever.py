"""Retriever agent."""

from app.agents.base import BaseAgent
from app.models.domain import Agent, AgentRole


class RetrieverAgent(BaseAgent):
    """Retrieve the stage-one built-in incident response knowledge."""

    @property
    def profile(self) -> Agent:
        return Agent(
            name="Retriever Agent",
            role=AgentRole.RETRIEVER,
            description="Retrieves relevant diagnostic evidence and knowledge.",
        )
