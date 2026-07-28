"""Retriever agent."""

from app.agents.base import BaseAgent
from app.agents.contracts import EvidenceBundle, RetrieverInput
from app.models.domain import Agent, AgentRole, Task
from app.protocol import MessageAction


class RetrieverAgent(BaseAgent):
    """Retrieve the stage-one built-in incident response knowledge."""

    system_prompt = (
        "You are Retriever Agent. Retrieve and rank evidence only. "
        "Do not produce the final answer or execute remediation actions."
    )
    structured_system_prompt = (
        system_prompt
        + " In structured mode, output only the json object defined by the "
        "appended EvidenceBundle Schema and complete example; never output "
        "Markdown or explanatory text."
    )
    capabilities = (
        "knowledge_retrieval",
        "keyword_search",
        "tag_search",
        "vector_search",
        "shared_memory_retrieval",
    )
    accepted_actions = (
        MessageAction.HANDSHAKE,
        MessageAction.RETRIEVE_EVIDENCE,
    )
    input_model_name = RetrieverInput.__name__
    output_model_name = EvidenceBundle.__name__
    allowed_tools = (
        "keyword_memory_search",
        "tag_memory_search",
        "vector_memory_search",
    )

    @property
    def profile(self) -> Agent:
        return Agent(
            name="Retriever Agent",
            role=AgentRole.RETRIEVER,
            description="Retrieves relevant diagnostic evidence and knowledge.",
        )

    def build_text_prompt(self, task: Task, input_text: str) -> str:
        return (
            f"任务：{task.title}\n原始问题：{task.prompt}\n"
            f"收到的完整规划：\n{input_text}\n"
            "仅补充相关知识、证据来源、相关度和置信度。"
        )

    async def retrieve(self, retriever_input: RetrieverInput) -> EvidenceBundle:
        """Return a validated evidence bundle without forming a conclusion."""

        try:
            generated = await self._llm.generate(
                system_prompt=self.structured_system_prompt,
                user_prompt=retriever_input.model_dump_json(),
                response_model=EvidenceBundle,
                context={
                    "role": "retriever",
                    "query": retriever_input.query_text,
                    "knowledge_items": retriever_input.knowledge_items,
                    "shared_memories": retriever_input.shared_memories,
                },
            )
        except Exception as exc:
            from app.agents.base import AgentExecutionError

            raise AgentExecutionError(f"Retriever failed: {exc}") from exc
        if not isinstance(generated, EvidenceBundle):
            raise TypeError("Retriever must return EvidenceBundle")
        return generated
