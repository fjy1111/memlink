"""Unified language-model and embedding adapters."""

from app.llm.clients import (
    LLMClient,
    LLMClientError,
    FakeLLMClient,
    OpenAICompatibleLLMClient,
    create_llm_client,
)
from app.llm.embeddings import (
    EmbeddingClient,
    EmbeddingClientError,
    FakeEmbeddingClient,
    OpenAICompatibleEmbeddingClient,
    create_embedding_client,
)

__all__ = [
    "EmbeddingClient",
    "EmbeddingClientError",
    "FakeEmbeddingClient",
    "FakeLLMClient",
    "LLMClient",
    "LLMClientError",
    "OpenAICompatibleEmbeddingClient",
    "OpenAICompatibleLLMClient",
    "create_embedding_client",
    "create_llm_client",
]
