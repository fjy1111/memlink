"""Deterministic fake and OpenAI-compatible embedding clients."""

import asyncio
import hashlib
from typing import Protocol

import httpx
import numpy as np
import numpy.typing as npt

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)
FloatVector = npt.NDArray[np.float32]


class EmbeddingClientError(RuntimeError):
    """Provider-neutral embedding failure."""


class EmbeddingClient(Protocol):
    """Interface for semantic vector generation."""

    @property
    def dimensions(self) -> int:
        """Return the expected embedding dimensionality."""

    async def embed(self, text: str) -> FloatVector:
        """Return a one-dimensional normalized float32 vector."""


class FakeEmbeddingClient:
    """Generate stable vectors by expanding a SHA-256 text hash."""

    def __init__(self, dimensions: int = 32) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self._dimensions = dimensions
        self.retry_count = 0

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> FloatVector:
        """Hash text into a deterministic, normalized non-text vector."""

        if not text.strip():
            raise ValueError("text must not be empty")
        raw = bytearray()
        counter = 0
        while len(raw) < self._dimensions:
            raw.extend(
                hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
            )
            counter += 1
        values = np.frombuffer(bytes(raw[: self._dimensions]), dtype=np.uint8)
        vector = (values.astype(np.float32) - np.float32(127.5)) / np.float32(127.5)
        norm = np.linalg.norm(vector)
        if norm == 0:
            vector[0] = 1.0
            norm = np.linalg.norm(vector)
        return np.ascontiguousarray(vector / norm, dtype=np.float32)


class OpenAICompatibleEmbeddingClient:
    """Provider-neutral ``/embeddings`` adapter."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Embedding API key is required")
        if not base_url:
            raise ValueError("Embedding base URL is required")
        if not model:
            raise ValueError("Embedding model is required")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._transport = transport
        self.retry_count = 0

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> FloatVector:
        """Call the configured embedding endpoint with bounded retries."""

        endpoint = f"{self.base_url}/embeddings"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload = {"model": self.model, "input": text}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    transport=self._transport,
                ) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
                    response.raise_for_status()
                values = response.json()["data"][0]["embedding"]
                vector = np.asarray(values, dtype=np.float32)
                if vector.ndim != 1 or vector.size != self.dimensions:
                    raise EmbeddingClientError(
                        f"Expected {self.dimensions} dimensions, received {vector.shape}"
                    )
                return np.ascontiguousarray(vector, dtype=np.float32)
            except (
                httpx.HTTPError,
                KeyError,
                TypeError,
                ValueError,
                EmbeddingClientError,
            ) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self.retry_count += 1
                    logger.warning(
                        "Embedding request attempt %d failed; retrying",
                        attempt + 1,
                    )
                    await asyncio.sleep(min(0.1 * (2**attempt), 1.0))
        raise EmbeddingClientError(
            "Embedding request failed after "
            f"{self.max_retries + 1} attempts: {last_error}"
        ) from last_error


def create_embedding_client(settings: Settings) -> EmbeddingClient:
    """Create the configured embedding adapter."""

    if settings.embedding_backend == "fake":
        return FakeEmbeddingClient(settings.embedding_dimensions)
    return OpenAICompatibleEmbeddingClient(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        timeout_seconds=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
    )
