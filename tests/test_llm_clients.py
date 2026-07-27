"""Offline tests for model and embedding adapters."""

import json

import httpx
import numpy as np
import pytest

from app.agents.contracts import TaskPlan
from app.core.config import Settings
from app.llm import (
    FakeEmbeddingClient,
    FakeLLMClient,
    OpenAICompatibleEmbeddingClient,
    OpenAICompatibleLLMClient,
    create_embedding_client,
    create_llm_client,
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
        metrics_dir=tmp_path / "metrics",
        state_dir=tmp_path / "states",
        memory_db_path=tmp_path / "memory.db",
    )

    assert isinstance(create_llm_client(settings), FakeLLMClient)
    assert isinstance(create_embedding_client(settings), FakeEmbeddingClient)
    assert "api_key" not in repr(settings).lower()


def test_openai_compatible_clients_require_configuration() -> None:
    with pytest.raises(ValueError, match="API key"):
        OpenAICompatibleLLMClient(
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


def test_openai_compatible_clients_are_vendor_neutral() -> None:
    llm = OpenAICompatibleLLMClient(
        api_key="test-secret",
        base_url="https://provider.example/v1",
        model="chat-model",
    )
    embedding = OpenAICompatibleEmbeddingClient(
        api_key="test-secret",
        base_url="https://provider.example/v1",
        model="embedding-model",
        dimensions=64,
    )

    assert llm.base_url == "https://provider.example/v1"
    assert llm.model == "chat-model"
    assert embedding.base_url == "https://provider.example/v1"
    assert embedding.model == "embedding-model"
    assert "test-secret" not in repr(llm)
    assert "test-secret" not in repr(embedding)


@pytest.mark.asyncio
async def test_openai_compatible_llm_retries_and_validates_without_network() -> None:
    attempts = 0
    plan_payload = {
        "goal": "diagnose",
        "steps": ["retrieve"],
        "dependencies": {},
        "assigned_capability": {"1": "knowledge_retrieval"},
        "risks": [],
        "success_criteria": ["evidence exists"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(plan_payload),
                        }
                    }
                ]
            },
        )

    client = OpenAICompatibleLLMClient(
        api_key="test-secret",
        base_url="https://provider.example/v1",
        model="chat-model",
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    result = await client.generate(
        system_prompt="plan",
        user_prompt="diagnose",
        response_model=TaskPlan,
    )

    assert result == TaskPlan.model_validate(plan_payload)
    assert attempts == 2
    assert client.retry_count == 1
