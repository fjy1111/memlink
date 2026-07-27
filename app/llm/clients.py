"""Fake and OpenAI-compatible language-model clients."""

import asyncio
import json
from typing import Any, Protocol, TypeVar, cast

import httpx
from pydantic import BaseModel

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)
ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class LLMClientError(RuntimeError):
    """Clear, provider-neutral model request failure."""


class LLMClient(Protocol):
    """Interface shared by offline and real model adapters."""

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str | ResponseModelT:
        """Generate validated text or a Pydantic response."""


class FakeLLMClient:
    """Deterministic offline implementation used by tests and demos."""

    retry_count = 0

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str | ResponseModelT:
        """Return stable content derived only from supplied context."""

        # Imported lazily so ``app.llm`` remains independently importable:
        # concrete agents depend on this client protocol, while these offline
        # fixtures depend only on their Pydantic contracts.
        from app.agents.contracts import (
            EvidenceBundle,
            EvidenceItem,
            ExecutionResult,
            ReviewResult,
            TaskPlan,
        )

        data = context or {}
        if response_model is None:
            role = data.get("role", "agent")
            if role == "planner":
                return (
                    f"任务规划：\n{user_prompt.strip()}\n"
                    "排查顺序：收集证据、验证假设、执行止损、复核恢复标准。"
                )
            if role == "retriever":
                return (
                    f"证据检索结果：\n{user_prompt.strip()}\n"
                    "参考请求量、错误率、延迟、资源饱和度、调用链和变更记录。"
                )
            if role == "executor":
                return (
                    f"安全执行结果：\n{user_prompt.strip()}\n"
                    "已模拟分析证据并准备可回滚的限流、扩容或回退方案。"
                )
            if role == "reviewer":
                return (
                    f"企业技术故障分析最终报告：\n{user_prompt.strip()}\n"
                    "结论必须由 evidence_id 支持，并通过恢复指标与最小实验复核。"
                )
            return f"[{role}] {user_prompt.strip()}"

        if response_model is TaskPlan:
            original_task = str(data.get("original_task", user_prompt))
            memory_summaries = list(data.get("memory_summaries", []))
            memory_risk = (
                ["复用记忆可能已过时，需要当前证据复核"]
                if memory_summaries
                else ["可观测数据不足可能导致根因判断偏差"]
            )
            value = TaskPlan(
                goal=f"定位并缓解：{original_task}",
                steps=[
                    "收集故障窗口内的指标、日志和调用链证据",
                    "执行安全的诊断分析并形成可验证结论",
                    "复核证据覆盖、矛盾和恢复标准",
                ],
                dependencies={"2": ["1"], "3": ["1", "2"]},
                assigned_capability={
                    "1": "knowledge_retrieval",
                    "2": "safe_execution",
                    "3": "evidence_review",
                },
                risks=memory_risk,
                success_criteria=[
                    "关键结论均关联有效 evidence_id",
                    "止损动作可回滚且有前后指标对照",
                ],
            )
        elif response_model is EvidenceBundle:
            query = str(data.get("query", user_prompt))
            knowledge_items = list(data.get("knowledge_items", []))
            shared_memories = list(data.get("shared_memories", []))
            candidates: list[tuple[str, str, str, float]] = []
            for index, content in enumerate(knowledge_items[:3], start=1):
                candidates.append(
                    (f"knowledge-{index}", str(content), "knowledge", 0.82 - index * 0.03)
                )
            for index, memory in enumerate(shared_memories[:3], start=1):
                memory_id = str(memory.get("memory_id", f"memory-{index}"))
                summary = str(memory.get("summary", memory))
                candidates.append((f"memory:{memory_id}", summary, "shared_memory", 0.9))
            if not candidates:
                candidates.append(
                    (
                        "knowledge-default",
                        "检查请求量、错误率、延迟、饱和度和最近变更。",
                        "knowledge",
                        0.75,
                    )
                )
            items = [
                EvidenceItem(
                    evidence_id=evidence_id,
                    content=content,
                    source_type=source_type,
                    relevance_score=score,
                )
                for evidence_id, content, source_type, score in candidates
            ]
            value = EvidenceBundle(
                query=query,
                evidence_items=items,
                evidence_ids=[item.evidence_id for item in items],
                source_types=[item.source_type for item in items],
                relevance_scores=[item.relevance_score for item in items],
                summary="；".join(item.content for item in items),
                confidence=min(0.95, sum(item.relevance_score for item in items) / len(items)),
            )
        elif response_model is ExecutionResult:
            evidence_ids = [str(item) for item in data.get("evidence_ids", [])]
            action = str(data.get("action", "analyze_incident"))
            value = ExecutionResult(
                action=action,
                success=True,
                result_summary=(
                    "已完成确定性诊断：优先核查变更、容量、依赖超时与资源饱和，"
                    "并准备可回滚的限流或回退方案。"
                ),
                result_ref=str(data.get("result_ref", "")) or None,
                evidence_ids=evidence_ids,
                error_code=None,
                retryable=False,
            )
        elif response_model is ReviewResult:
            execution_success = bool(data.get("execution_success", False))
            evidence_ids = [str(item) for item in data.get("evidence_ids", [])]
            original_task = str(data.get("original_task", user_prompt))
            passed = execution_success and bool(evidence_ids)
            value = ReviewResult(
                passed=passed,
                final_answer=(
                    f"任务“{original_task}”已完成证据化分析。"
                    "建议先保存故障窗口数据，再依据指标、日志和调用链缩小范围；"
                    "影响持续时采用可回滚的限流、扩容或版本回退，并通过恢复指标"
                    "和最小复现实验确认根因。"
                ),
                missing_evidence=[] if evidence_ids else ["缺少 evidence_id"],
                contradictions=[],
                recommendations=[
                    "持续监测 P95 延迟、错误率与资源饱和度",
                    "将验证过的排查策略保存为共享记忆",
                ],
                confidence=0.9 if passed else 0.4,
                should_store_memory=passed,
            )
        else:
            raise LLMClientError(
                f"FakeLLMClient has no fixture for {response_model.__name__}"
            )
        return cast(ResponseModelT, value)


class OpenAICompatibleLLMClient:
    """Provider-neutral chat-completions adapter using ``httpx``."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        temperature: float = 0.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("LLM API key is required for openai_compatible backend")
        if not base_url:
            raise ValueError("LLM base URL is required for openai_compatible backend")
        if not model:
            raise ValueError("LLM model is required for openai_compatible backend")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.temperature = temperature
        self._transport = transport
        self.retry_count = 0

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str | ResponseModelT:
        """Call a configured OpenAI-compatible chat endpoint with retries."""

        del context
        schema_instruction = ""
        if response_model is not None:
            schema_instruction = (
                "\nReturn only a JSON object matching this schema:\n"
                + json.dumps(
                    response_model.model_json_schema(),
                    ensure_ascii=False,
                )
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_prompt + schema_instruction},
                {"role": "user", "content": user_prompt},
            ],
        }
        if response_model is not None:
            payload["response_format"] = {"type": "json_object"}

        endpoint = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    transport=self._transport,
                ) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
                    response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise LLMClientError("Model returned empty content")
                if response_model is None:
                    return content
                return response_model.model_validate_json(content)
            except (
                httpx.HTTPError,
                KeyError,
                TypeError,
                ValueError,
                LLMClientError,
            ) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self.retry_count += 1
                    logger.warning(
                        "LLM request attempt %d failed; retrying",
                        attempt + 1,
                    )
                    await asyncio.sleep(min(0.1 * (2**attempt), 1.0))
        raise LLMClientError(
            f"LLM request failed after {self.max_retries + 1} attempts: {last_error}"
        ) from last_error


def create_llm_client(settings: Settings) -> LLMClient:
    """Create the configured language-model adapter without vendor coupling."""

    if settings.llm_backend == "fake":
        return FakeLLMClient()
    return OpenAICompatibleLLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=settings.llm_temperature,
    )
