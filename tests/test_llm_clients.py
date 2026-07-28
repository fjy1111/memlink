"""Offline tests for model and embedding adapters."""

import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from app.agents.contracts import TaskPlan
from app.core.config import Settings
from app.llm import (
    DeepSeekLLMClient,
    FakeEmbeddingClient,
    FakeLLMClient,
    LLMClientError,
    OpenAICompatibleEmbeddingClient,
    create_embedding_client,
    create_llm_client,
)
from app.models import CommunicationMode, LLMBackend, TaskCreate
from app.runtime.orchestrator import TaskOrchestrator

TEST_API_KEY = "test-only-deepseek-secret"
PLAN_PAYLOAD = {
    "goal": "diagnose",
    "steps": ["retrieve"],
    "dependencies": {},
    "assigned_capability": {"1": "knowledge_retrieval"},
    "risks": [],
    "success_criteria": ["evidence exists"],
}


def chat_completion_response(
    content: str | None,
    *,
    finish_reason: str = "stop",
    reasoning_content: str | None = None,
    tool_calls: list[dict[str, object]] | None = None,
) -> httpx.Response:
    """Build one local DeepSeek-shaped response without network access."""

    message: dict[str, object] = {"content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": message,
                }
            ]
        },
    )


@pytest.mark.asyncio
async def test_fake_llm_is_deterministic_and_validated() -> None:
    client = FakeLLMClient()
    arguments = {
        "system_prompt": "You are the planner.",
        "user_prompt": "Analyze API latency.",
        "response_model": TaskPlan,
        "context": {"original_task": "Analyze API latency."},
    }

    first = await client.generate(**arguments)
    second = await client.generate(**arguments)

    assert isinstance(first, TaskPlan)
    assert first == second
    assert first.assigned_capability["1"] == "knowledge_retrieval"


@pytest.mark.asyncio
async def test_fake_embedding_is_stable_float_vector() -> None:
    client = FakeEmbeddingClient(dimensions=16)

    first = await client.embed("same text")
    second = await client.embed("same text")
    different = await client.embed("different text")

    assert first.dtype == np.float32
    assert first.shape == (16,)
    assert np.array_equal(first, second)
    assert not np.array_equal(first, different)
    assert np.isclose(np.linalg.norm(first), 1.0)


def test_factories_default_to_fake_without_secrets(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        metrics_dir=tmp_path / "metrics",
        state_dir=tmp_path / "states",
        memory_db_path=tmp_path / "memory.db",
    )

    assert isinstance(create_llm_client(settings), FakeLLMClient)
    assert isinstance(create_embedding_client(settings), FakeEmbeddingClient)
    assert "api_key" not in repr(settings).lower()


def test_deepseek_client_requires_configuration_without_exposing_key() -> None:
    with pytest.raises(ValueError, match="API Key"):
        DeepSeekLLMClient(
            api_key="",
            base_url="https://example.invalid/v1",
            model="model",
        )
    with pytest.raises(ValueError, match="base URL"):
        OpenAICompatibleEmbeddingClient(
            api_key="secret",
            base_url="",
            model="embedding-model",
            dimensions=32,
        )


def test_deepseek_settings_load_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMLINK_LLM_BACKEND", "deepseek")
    monkeypatch.setenv("MEMLINK_DEEPSEEK_API_KEY", TEST_API_KEY)
    monkeypatch.setenv(
        "MEMLINK_DEEPSEEK_BASE_URL",
        "https://deepseek.example/v1",
    )
    monkeypatch.setenv("MEMLINK_DEEPSEEK_MODEL", "deepseek-test")
    monkeypatch.setenv("MEMLINK_LLM_MAX_TOKENS", "987")

    settings = Settings(_env_file=None)

    assert settings.llm_backend == "deepseek"
    assert settings.deepseek_api_key == TEST_API_KEY
    assert settings.deepseek_base_url == "https://deepseek.example/v1"
    assert settings.deepseek_model == "deepseek-test"
    assert settings.llm_max_tokens == 987
    assert TEST_API_KEY not in repr(settings)


def test_deepseek_factory_requires_api_key(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        llm_backend="deepseek",
        deepseek_base_url="https://example.invalid/v1",
        deepseek_model="test-model",
        metrics_dir=tmp_path / "metrics",
        state_dir=tmp_path / "states",
        memory_db_path=tmp_path / "memory.db",
    )

    with pytest.raises(ValueError, match="API Key") as captured:
        create_llm_client(settings)

    assert TEST_API_KEY not in str(captured.value)


def test_clients_do_not_expose_test_secret_in_repr() -> None:
    llm = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
    )
    embedding = OpenAICompatibleEmbeddingClient(
        api_key=TEST_API_KEY,
        base_url="https://provider.example/v1",
        model="embedding-model",
        dimensions=64,
    )

    assert llm.base_url == "https://deepseek.example/v1"
    assert llm.model == "deepseek-test"
    assert embedding.base_url == "https://provider.example/v1"
    assert embedding.model == "embedding-model"
    assert TEST_API_KEY not in repr(llm)
    assert TEST_API_KEY not in repr(embedding)


@pytest.mark.asyncio
async def test_deepseek_request_format_retries_and_validates_offline() -> None:
    attempts = 0
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts, captured_request
        attempts += 1
        captured_request = request
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return chat_completion_response(json.dumps(PLAN_PAYLOAD))

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=1,
        temperature=0.2,
        max_tokens=777,
        transport=httpx.MockTransport(handler),
    )

    result = await client.generate(
        system_prompt="plan",
        user_prompt="diagnose",
        response_model=TaskPlan,
    )

    assert result == TaskPlan.model_validate(PLAN_PAYLOAD)
    assert attempts == 2
    assert client.retry_count == 1
    assert captured_request is not None
    request_payload = json.loads(captured_request.content)
    assert str(captured_request.url) == (
        "https://deepseek.example/v1/chat/completions"
    )
    assert captured_request.headers["Authorization"] == f"Bearer {TEST_API_KEY}"
    assert request_payload["model"] == "deepseek-test"
    assert request_payload["temperature"] == 0.2
    assert request_payload["max_tokens"] == 4096
    assert request_payload["response_format"] == {"type": "json_object"}
    assert request_payload["thinking"] == {"type": "disabled"}
    system_content = request_payload["messages"][0]["content"]
    assert "valid json object" in system_content
    assert "COMPLETE JSON EXAMPLE" in system_content
    assert '"goal"' in system_content


@pytest.mark.asyncio
async def test_deepseek_valid_structured_json_succeeds_once() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return chat_completion_response(json.dumps(PLAN_PAYLOAD))

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        transport=httpx.MockTransport(handler),
    )

    result = await client.generate(
        system_prompt="You are Planner Agent.",
        user_prompt="plan",
        response_model=TaskPlan,
        context={"role": "planner"},
    )

    assert result == TaskPlan.model_validate(PLAN_PAYLOAD)
    assert attempts == 1


@pytest.mark.asyncio
async def test_deepseek_empty_content_then_valid_json_retries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return chat_completion_response("")
        request_payload = json.loads(request.content)
        repair_prompt = request_payload["messages"][1]["content"]
        assert "STRUCTURED JSON REPAIR REQUEST" in repair_prompt
        assert "content 为空" in repair_prompt
        assert "COMPLETE JSON EXAMPLE" in repair_prompt
        return chat_completion_response(json.dumps(PLAN_PAYLOAD))

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    result = await client.generate(
        system_prompt="You are Planner Agent.",
        user_prompt="plan",
        response_model=TaskPlan,
        context={"role": "planner"},
    )

    assert isinstance(result, TaskPlan)
    assert attempts == 2
    assert client.retry_count == 1
    assert "category=empty_content" in caplog.text


@pytest.mark.asyncio
async def test_deepseek_invalid_json_then_valid_json_retries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return chat_completion_response('{"goal": "broken"')
        request_payload = json.loads(request.content)
        repair_prompt = request_payload["messages"][1]["content"]
        assert "不是合法 json" in repair_prompt
        assert "TARGET JSON SCHEMA" in repair_prompt
        return chat_completion_response(json.dumps(PLAN_PAYLOAD))

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    result = await client.generate(
        system_prompt="You are Planner Agent.",
        user_prompt="plan",
        response_model=TaskPlan,
    )

    assert isinstance(result, TaskPlan)
    assert attempts == 2
    assert "category=json_parse_failed" in caplog.text


@pytest.mark.asyncio
async def test_deepseek_missing_required_fields_reports_schema_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_completion_response(json.dumps({"goal": "diagnose"}))

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        LLMClientError,
        match="Schema 校验失败：缺少必填字段",
    ) as captured:
        await client.generate(
            system_prompt="You are Planner Agent.",
            user_prompt="plan",
            response_model=TaskPlan,
        )

    message = str(captured.value)
    assert "steps" in message
    assert "success_criteria" in message
    assert TEST_API_KEY not in message


@pytest.mark.asyncio
async def test_deepseek_wrong_field_type_reports_schema_error() -> None:
    invalid_payload = {
        **PLAN_PAYLOAD,
        "steps": "retrieve",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return chat_completion_response(json.dumps(invalid_payload))

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        LLMClientError,
        match="字段类型或约束错误：steps",
    ):
        await client.generate(
            system_prompt="You are Planner Agent.",
            user_prompt="plan",
            response_model=TaskPlan,
        )


@pytest.mark.asyncio
async def test_deepseek_accepts_one_markdown_json_fence() -> None:
    fenced = "```json\n" + json.dumps(PLAN_PAYLOAD) + "\n```"

    def handler(request: httpx.Request) -> httpx.Response:
        return chat_completion_response(fenced)

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        transport=httpx.MockTransport(handler),
    )

    result = await client.generate(
        system_prompt="You are Planner Agent.",
        user_prompt="plan",
        response_model=TaskPlan,
    )

    assert result == TaskPlan.model_validate(PLAN_PAYLOAD)


@pytest.mark.asyncio
async def test_deepseek_finish_reason_length_is_distinct() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_completion_response(
            '{"goal":"truncated"',
            finish_reason="length",
        )

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        LLMClientError,
        match="finish_reason=length",
    ):
        await client.generate(
            system_prompt="You are Planner Agent.",
            user_prompt="plan",
            response_model=TaskPlan,
        )


@pytest.mark.asyncio
async def test_reasoning_content_is_never_used_as_structured_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="app.llm.clients")
    hidden_reasoning = "private-reasoning-must-not-be-logged"

    def handler(request: httpx.Request) -> httpx.Response:
        return chat_completion_response(
            None,
            reasoning_content=hidden_reasoning,
        )

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        LLMClientError,
        match="reasoning_content 存在",
    ):
        await client.generate(
            system_prompt="You are Planner Agent.",
            user_prompt="plan",
            response_model=TaskPlan,
        )

    assert hidden_reasoning not in caplog.text
    assert f"reasoning_content_chars={len(hidden_reasoning)}" in caplog.text


@pytest.mark.asyncio
async def test_deepseek_repeated_empty_content_fails_without_fake_fallback() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return chat_completion_response("")

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMClientError, match="返回空 content"):
        await client.generate(
            system_prompt="You are Planner Agent.",
            user_prompt="plan",
            response_model=TaskPlan,
        )

    assert attempts == 3
    assert client.retry_count == 2


@pytest.mark.asyncio
async def test_deepseek_text_mode_keeps_plain_content_and_default_thinking() -> None:
    captured_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content))
        return chat_completion_response("plain text answer")

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        transport=httpx.MockTransport(handler),
    )

    result = await client.generate(
        system_prompt="You are Planner Agent.",
        user_prompt="plan",
        context={"role": "planner"},
    )

    assert result == "plain text answer"
    assert "response_format" not in captured_payload
    assert "thinking" not in captured_payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_status", "expected_message"),
    [
        (401, "认证失败（HTTP 401）"),
        (403, "拒绝访问（HTTP 403）"),
        (429, "请求频率受限（HTTP 429）"),
    ],
)
async def test_deepseek_http_errors_are_redacted(
    response_status: int,
    expected_message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            response_status,
            json={"error": f"must hide {TEST_API_KEY}"},
        )

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMClientError, match=expected_message) as captured:
        await client.generate(system_prompt="system", user_prompt="user")

    assert TEST_API_KEY not in str(captured.value)
    assert TEST_API_KEY not in caplog.text


@pytest.mark.asyncio
async def test_deepseek_timeout_is_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            f"timeout with hidden {TEST_API_KEY}",
            request=request,
        )

    client = DeepSeekLLMClient(
        api_key=TEST_API_KEY,
        base_url="https://deepseek.example/v1",
        model="deepseek-test",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMClientError, match="请求超时") as captured:
        await client.generate(system_prompt="system", user_prompt="user")

    assert TEST_API_KEY not in str(captured.value)
    assert TEST_API_KEY not in caplog.text


def _four_agent_response(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    system_prompt = payload["messages"][0]["content"]
    if "response_format" not in payload:
        content: str | dict[str, object] = "角色独立完成本次文本交接。"
    elif '"evidence_items"' in system_prompt:
        content = {
            "query": "incident",
            "evidence_items": [
                {
                    "evidence_id": "evidence-1",
                    "content": "P95 latency increased after a deployment.",
                    "source_type": "knowledge",
                    "relevance_score": 0.9,
                }
            ],
            "evidence_ids": ["evidence-1"],
            "source_types": ["knowledge"],
            "relevance_scores": [0.9],
            "summary": "Deployment and latency evidence.",
            "confidence": 0.9,
        }
    elif '"result_summary"' in system_prompt:
        content = {
            "action": "analyze_incident",
            "success": True,
            "result_summary": "A reversible rollback is recommended.",
            "result_ref": None,
            "evidence_ids": ["evidence-1"],
            "error_code": None,
            "retryable": False,
        }
    elif '"final_answer"' in system_prompt:
        content = {
            "passed": True,
            "final_answer": "Rollback and verify P95 recovery.",
            "missing_evidence": [],
            "contradictions": [],
            "recommendations": ["Monitor P95 latency."],
            "confidence": 0.9,
            "should_store_memory": True,
        }
    else:
        content = {
            "goal": "Diagnose the incident.",
            "steps": ["Retrieve evidence.", "Analyze.", "Review."],
            "dependencies": {"2": ["1"], "3": ["1", "2"]},
            "assigned_capability": {
                "1": "knowledge_retrieval",
                "2": "safe_execution",
                "3": "evidence_review",
            },
            "risks": [],
            "success_criteria": ["Evidence exists."],
        }
    return chat_completion_response(
        content if isinstance(content, str) else json.dumps(content)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [CommunicationMode.TEXT, CommunicationMode.STRUCTURED],
)
async def test_both_modes_call_deepseek_once_per_agent(
    mode: CommunicationMode,
    tmp_path: Path,
) -> None:
    call_count = 0
    system_prompts: list[str] = []
    request_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        request_payload = json.loads(request.content)
        request_payloads.append(request_payload)
        system_prompts.append(request_payload["messages"][0]["content"])
        return _four_agent_response(request)

    orchestrator = TaskOrchestrator(
        metrics_dir=tmp_path / mode.value / "metrics",
        state_dir=tmp_path / mode.value / "states",
        memory_db_path=tmp_path / mode.value / "memory.db",
        llm=DeepSeekLLMClient(
            api_key=TEST_API_KEY,
            base_url="https://deepseek.example/v1",
            model="deepseek-test",
            transport=httpx.MockTransport(handler),
        ),
        embedding=FakeEmbeddingClient(),
        backend_name="deepseek",
    )

    result = await orchestrator.run(
        TaskCreate(
            title="DeepSeek offline integration",
            prompt="Diagnose latency using four distinct roles.",
            task_topic="deepseek-integration",
            mode=mode,
            llm_backend=LLMBackend.DEEPSEEK,
        )
    )

    assert call_count == 4
    assert [
        prompt.split(" Agent.", maxsplit=1)[0]
        for prompt in system_prompts
    ] == [
        "You are Planner",
        "You are Retriever",
        "You are Executor",
        "You are Reviewer",
    ]
    assert result.agent_trace == [
        "planner",
        "retriever",
        "executor",
        "reviewer",
    ]
    if mode is CommunicationMode.STRUCTURED:
        assert all(
            payload["thinking"] == {"type": "disabled"}
            for payload in request_payloads
        )
        assert all(
            payload["response_format"] == {"type": "json_object"}
            for payload in request_payloads
        )
        assert all(
            "COMPLETE JSON EXAMPLE" in prompt
            and "valid json object" in prompt
            for prompt in system_prompts
        )
        assert all(
            schema_name in prompt
            for schema_name, prompt in zip(
                (
                    "TaskPlan",
                    "EvidenceBundle",
                    "ExecutionResult",
                    "ReviewResult",
                ),
                system_prompts,
                strict=True,
            )
        )
    else:
        assert all("thinking" not in payload for payload in request_payloads)
        assert all(
            "response_format" not in payload for payload in request_payloads
        )
