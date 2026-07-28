"""Fake and DeepSeek language-model clients."""

import asyncio
import json
import re
from collections.abc import Mapping
from typing import Any, Protocol, TypeVar, cast

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)
ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class LLMClientError(RuntimeError):
    """Clear, provider-neutral model request failure."""


class _LLMResponseError(LLMClientError):
    """Redacted, categorized response failure used for bounded retries."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        repair_hint: str,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.repair_hint = repair_hint
        self.retryable = retryable


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
    """Reusable OpenAI-compatible chat-completions transport."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        temperature: float = 0.0,
        max_tokens: int = 1500,
        provider_name: str = "OpenAI-compatible",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip() or api_key.strip() == "replace-me":
            raise ValueError(f"{provider_name} API Key 未配置")
        if (
            not base_url.strip()
            or not base_url.startswith(("https://", "http://"))
            or "replace-with-" in base_url
        ):
            raise ValueError(f"{provider_name} Base URL 未配置")
        if not model.strip() or model.startswith("replace-with-"):
            raise ValueError(f"{provider_name} 模型名称未配置")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.provider_name = provider_name
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

        data = context or {}
        structured = response_model is not None
        agent_role = str(
            data.get("role")
            or self._infer_agent_role(response_model)
        )
        schema_instruction = (
            self._structured_instruction(response_model)
            if response_model is not None
            else ""
        )
        endpoint = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_error = f"{self.provider_name} 请求失败"
        repair_hint = ""
        for attempt in range(self.max_retries + 1):
            current_user_prompt = user_prompt
            if structured and repair_hint:
                current_user_prompt += self._repair_instruction(
                    response_model,
                    repair_hint,
                )
            request_max_tokens = (
                max(self.max_tokens, 4096)
                if structured
                else self.max_tokens
            )
            payload: dict[str, Any] = {
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": request_max_tokens,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt + schema_instruction,
                    },
                    {"role": "user", "content": current_user_prompt},
                ],
            }
            if structured:
                payload["response_format"] = {"type": "json_object"}
                payload["thinking"] = {"type": "disabled"}
            logger.info(
                "LLM request provider=%s model=%s agent=%s attempt=%d "
                "json_mode=%s thinking=%s max_tokens=%d",
                self.provider_name.lower(),
                self.model,
                agent_role,
                attempt + 1,
                structured,
                "disabled" if structured else "default",
                request_max_tokens,
            )
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    transport=self._transport,
                ) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
                    response.raise_for_status()
                body = self._decode_response_body(response)
                (
                    content,
                    finish_reason,
                    reasoning_chars,
                    has_tool_calls,
                ) = self._extract_response(body)
                logger.info(
                    "LLM response provider=%s model=%s agent=%s attempt=%d "
                    "http_status=%d finish_reason=%s content_chars=%d "
                    "reasoning_content_chars=%d json_mode=%s thinking=%s "
                    "tool_calls=%s",
                    self.provider_name.lower(),
                    self.model,
                    agent_role,
                    attempt + 1,
                    response.status_code,
                    finish_reason,
                    len(content) if isinstance(content, str) else 0,
                    reasoning_chars,
                    structured,
                    "disabled" if structured else "default",
                    has_tool_calls,
                )
                if finish_reason == "length":
                    raise _LLMResponseError(
                        f"{self.provider_name} 响应因 finish_reason=length "
                        "被截断",
                        category="truncated",
                        repair_hint=(
                            "上次 json 响应被截断；请缩短字符串内容，但仍返回"
                            "包含全部必填字段的完整 json 对象。"
                        ),
                    )
                if not isinstance(content, str) or not content.strip():
                    if has_tool_calls:
                        detail = "返回了 tool_calls，但没有最终 content"
                        category = "tool_calls_without_content"
                    elif reasoning_chars:
                        detail = (
                            "返回空 content；reasoning_content 存在但不会被"
                            "当作业务结果"
                        )
                        category = "reasoning_without_content"
                    else:
                        detail = "返回空 content"
                        category = "empty_content"
                    raise _LLMResponseError(
                        f"{self.provider_name} {detail}",
                        category=category,
                        repair_hint=(
                            "上次响应的 content 为空；请直接返回完整 json "
                            "对象，不要只生成推理内容或工具调用。"
                            if structured
                            else "上次响应为空；请返回最终文本答案。"
                        ),
                    )
                if response_model is None:
                    return content.strip()
                return self._validate_structured_content(
                    content,
                    response_model,
                    agent_role=agent_role,
                    attempt=attempt + 1,
                )
            except _LLMResponseError as exc:
                last_error = str(exc)
                retryable = exc.retryable
                repair_hint = exc.repair_hint
                logger.warning(
                    "LLM validation failed provider=%s model=%s agent=%s "
                    "attempt=%d category=%s error=%s",
                    self.provider_name.lower(),
                    self.model,
                    agent_role,
                    attempt + 1,
                    exc.category,
                    last_error,
                )
            except (
                httpx.HTTPError,
                KeyError,
                TypeError,
                ValueError,
                LLMClientError,
            ) as exc:
                last_error, retryable = self._safe_error(exc)
                http_status = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else "none"
                )
                repair_hint = (
                    "上次请求失败；重新返回目标 Schema 对应的完整 json 对象。"
                    if structured
                    else ""
                )
                logger.warning(
                    "LLM request failed provider=%s model=%s agent=%s "
                    "attempt=%d http_status=%s error=%s",
                    self.provider_name.lower(),
                    self.model,
                    agent_role,
                    attempt + 1,
                    http_status,
                    last_error,
                )
            if retryable and attempt < self.max_retries:
                self.retry_count += 1
                logger.warning(
                    "LLM retry provider=%s model=%s agent=%s next_attempt=%d",
                    self.provider_name.lower(),
                    self.model,
                    agent_role,
                    attempt + 2,
                )
                await asyncio.sleep(min(0.1 * (2**attempt), 1.0))
                continue
            break
        raise LLMClientError(last_error) from None

    def _decode_response_body(
        self,
        response: httpx.Response,
    ) -> Mapping[str, Any]:
        """Decode the HTTP response envelope without exposing its content."""

        try:
            body = response.json()
        except ValueError:
            raise _LLMResponseError(
                f"{self.provider_name} HTTP 响应不是有效 JSON",
                category="invalid_response_envelope",
                repair_hint="请返回标准 Chat Completions JSON 响应。",
            ) from None
        if not isinstance(body, Mapping):
            raise _LLMResponseError(
                f"{self.provider_name} HTTP 响应顶层格式无效",
                category="invalid_response_envelope",
                repair_hint="请返回标准 Chat Completions JSON 响应。",
            )
        return body

    def _extract_response(
        self,
        body: Mapping[str, Any],
    ) -> tuple[Any, str, int, bool]:
        """Validate choices/message and return only safe response metadata."""

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise _LLMResponseError(
                f"{self.provider_name} 响应缺少 choices",
                category="missing_choices",
                repair_hint="请返回包含一个有效 choice 的响应。",
            )
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise _LLMResponseError(
                f"{self.provider_name} choice 格式无效",
                category="invalid_choice",
                repair_hint="请返回标准 Chat Completions choice。",
            )
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise _LLMResponseError(
                f"{self.provider_name} 响应缺少 message",
                category="missing_message",
                repair_hint="请返回包含 message.content 的响应。",
            )
        finish_reason = str(choice.get("finish_reason") or "unknown")
        reasoning = message.get("reasoning_content")
        reasoning_chars = len(reasoning) if isinstance(reasoning, str) else 0
        tool_calls = message.get("tool_calls")
        has_tool_calls = isinstance(tool_calls, list) and bool(tool_calls)
        return (
            message.get("content"),
            finish_reason,
            reasoning_chars,
            has_tool_calls,
        )

    def _validate_structured_content(
        self,
        content: str,
        response_model: type[ResponseModelT],
        *,
        agent_role: str,
        attempt: int,
    ) -> ResponseModelT:
        """Strip optional fences, parse JSON, then enforce the Pydantic model."""

        normalized = self._strip_json_fence(content)
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError as exc:
            logger.info(
                "LLM structured validation provider=%s model=%s agent=%s "
                "attempt=%d json_parse=failed schema_validation=not_run",
                self.provider_name.lower(),
                self.model,
                agent_role,
                attempt,
            )
            raise _LLMResponseError(
                f"{self.provider_name} JSON 解析失败"
                f"（第 {exc.lineno} 行第 {exc.colno} 列）",
                category="json_parse_failed",
                repair_hint=(
                    "上次 content 不是合法 json；请只返回一个语法正确、"
                    "无 Markdown 的 json 对象。"
                ),
            ) from None
        if not isinstance(parsed, dict):
            raise _LLMResponseError(
                f"{self.provider_name} JSON 顶层必须是对象",
                category="json_not_object",
                repair_hint="请返回 json 对象，不要返回数组或普通文本。",
            )
        logger.info(
            "LLM structured validation provider=%s model=%s agent=%s "
            "attempt=%d json_parse=success schema_validation=pending",
            self.provider_name.lower(),
            self.model,
            agent_role,
            attempt,
        )
        try:
            validated = response_model.model_validate(parsed)
        except ValidationError as exc:
            missing_fields = sorted(
                ".".join(str(part) for part in error["loc"])
                for error in exc.errors(include_input=False)
                if error["type"] == "missing"
            )
            invalid_fields = sorted(
                {
                    ".".join(str(part) for part in error["loc"]) or "<root>"
                    for error in exc.errors(include_input=False)
                    if error["type"] != "missing"
                }
            )
            if missing_fields:
                detail = "缺少必填字段：" + ", ".join(missing_fields)
                category = "schema_missing_fields"
                repair_hint = (
                    "上次 json 缺少必填字段 "
                    + ", ".join(missing_fields)
                    + "；请按 Schema 补齐并返回完整 json。"
                )
            else:
                detail = "字段类型或约束错误：" + ", ".join(invalid_fields)
                category = "schema_invalid_fields"
                repair_hint = (
                    "上次 json 的字段类型或约束不正确；请严格按照 Schema "
                    "和示例重新生成。"
                )
            logger.info(
                "LLM structured validation provider=%s model=%s agent=%s "
                "attempt=%d json_parse=success schema_validation=failed "
                "category=%s",
                self.provider_name.lower(),
                self.model,
                agent_role,
                attempt,
                category,
            )
            raise _LLMResponseError(
                f"{self.provider_name} Schema 校验失败：{detail}",
                category=category,
                repair_hint=repair_hint,
            ) from None
        logger.info(
            "LLM structured validation provider=%s model=%s agent=%s "
            "attempt=%d json_parse=success schema_validation=success",
            self.provider_name.lower(),
            self.model,
            agent_role,
            attempt,
        )
        return validated

    @staticmethod
    def _strip_json_fence(content: str) -> str:
        """Accept one accidental Markdown fence while prompts still forbid it."""

        stripped = content.strip()
        fenced = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```",
            stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return fenced.group(1).strip() if fenced else stripped

    @staticmethod
    def _infer_agent_role(
        response_model: type[BaseModel] | None,
    ) -> str:
        roles = {
            "TaskPlan": "planner",
            "EvidenceBundle": "retriever",
            "ExecutionResult": "executor",
            "ReviewResult": "reviewer",
        }
        if response_model is None:
            return "unknown"
        return roles.get(response_model.__name__, "unknown")

    @staticmethod
    def _structured_instruction(
        response_model: type[BaseModel],
    ) -> str:
        """Build explicit lowercase-json rules, Schema, and complete example."""

        schema = response_model.model_json_schema()
        examples = schema.get("examples")
        example = examples[0] if isinstance(examples, list) and examples else {}
        return (
            "\n\nSTRICT STRUCTURED OUTPUT RULES:\n"
            "- Output exactly one valid json object and nothing else.\n"
            "- Do not output Markdown, explanations, commentary, or code fences.\n"
            "- Do not wrap the object in a triple-backtick json block.\n"
            "- Include every required field with the exact data type shown below.\n"
            "- The json must satisfy the target Schema and semantic constraints.\n"
            "TARGET JSON SCHEMA (required fields and field types):\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            + "\nCOMPLETE JSON EXAMPLE:\n"
            + json.dumps(example, ensure_ascii=False, separators=(",", ":"))
        )

    def _repair_instruction(
        self,
        response_model: type[BaseModel] | None,
        repair_hint: str,
    ) -> str:
        """Repeat safe repair guidance without echoing model output or errors."""

        if response_model is None:
            return "\n\nReturn a non-empty final text answer."
        return (
            "\n\nSTRUCTURED JSON REPAIR REQUEST:\n"
            + repair_hint
            + self._structured_instruction(response_model)
        )

    def _safe_error(self, error: Exception) -> tuple[str, bool]:
        """Return a redacted user-facing error and whether it is retryable."""

        prefix = self.provider_name
        if isinstance(error, httpx.TimeoutException):
            return f"{prefix} 请求超时，请检查网络或增大超时时间", True
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            if status == 401:
                return f"{prefix} 认证失败（HTTP 401），请检查 API Key", False
            if status == 403:
                return f"{prefix} 拒绝访问（HTTP 403），请检查权限", False
            if status == 402:
                return f"{prefix} 账户余额不足（HTTP 402）", False
            if status == 429:
                return f"{prefix} 请求频率受限（HTTP 429），请稍后重试", True
            if status >= 500:
                return f"{prefix} 服务暂时不可用（HTTP {status}）", True
            return f"{prefix} 请求被拒绝（HTTP {status}）", False
        if isinstance(error, httpx.TransportError):
            return f"{prefix} 网络请求失败，请检查网络和 Base URL", True
        if isinstance(error, (KeyError, TypeError)):
            return f"{prefix} 返回了无法识别的响应格式", True
        if isinstance(error, ValueError):
            return f"{prefix} 返回内容未通过结构化校验", True
        if isinstance(error, LLMClientError):
            return f"{prefix} 返回了空内容", True
        return f"{prefix} 请求失败", False


class DeepSeekLLMClient(OpenAICompatibleLLMClient):
    """DeepSeek chat client built on the existing compatible transport."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            temperature=temperature,
            max_tokens=max_tokens,
            provider_name="DeepSeek",
            transport=transport,
        )


def create_llm_client(settings: Settings) -> LLMClient:
    """Create the configured Fake or DeepSeek language-model adapter."""

    if settings.llm_backend == "fake":
        return FakeLLMClient()
    if settings.llm_backend != "deepseek":
        raise ValueError(f"Unsupported LLM backend: {settings.llm_backend}")
    return DeepSeekLLMClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
