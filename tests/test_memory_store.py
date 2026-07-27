"""SQLite shared-memory CRUD, retrieval, and reuse tests."""

from pathlib import Path

import pytest

from app.llm import FakeEmbeddingClient
from app.memory import MemoryType, SQLiteSharedMemoryStore, SharedMemory
from app.state import StateStore


def make_memory(
    *,
    semantic_state_id: str | None = None,
    summary: str = "RAG 延迟排查策略",
) -> SharedMemory:
    return SharedMemory(
        task_topic="enterprise-rag",
        source_agent="reviewer",
        memory_type=MemoryType.STRATEGY,
        summary=summary,
        content="检查检索耗时、生成耗时、依赖超时和并发资源饱和度。",
        tags=["rag", "latency", "incident"],
        evidence_ids=["evidence-1"],
        semantic_state_id=semantic_state_id,
        confidence=0.9,
    )


def test_memory_crud_and_basic_deduplication(tmp_path: Path) -> None:
    database_path = tmp_path / "memory" / "shared.db"
    store = SQLiteSharedMemoryStore(database_path)
    original = make_memory()

    stored = store.add(original)
    duplicate = store.add(
        original.model_copy(
            update={
                "memory_id": "duplicate-id",
                "tags": ["rag", "capacity"],
                "evidence_ids": ["evidence-2"],
                "confidence": 0.95,
            }
        )
    )
    fetched = store.get(stored.memory_id)

    assert duplicate.memory_id == stored.memory_id
    assert fetched.confidence == 0.95
    assert set(fetched.tags) == {"rag", "latency", "incident", "capacity"}
    assert set(fetched.evidence_ids) == {"evidence-1", "evidence-2"}
    assert database_path.is_file()

    renamed = database_path.with_suffix(".moved")
    database_path.replace(renamed)
    renamed.replace(database_path)


def test_keyword_and_tag_search_increment_usage(tmp_path: Path) -> None:
    store = SQLiteSharedMemoryStore(tmp_path / "shared.db")
    memory = store.add(make_memory())

    keyword_hits = store.search_keyword("enterprise-rag")
    tag_hits = store.search_tags(["rag", "missing"])

    assert keyword_hits[0].memory.memory_id == memory.memory_id
    assert tag_hits[0].memory.memory_id == memory.memory_id
    assert tag_hits[0].score == 0.5
    assert store.get(memory.memory_id).usage_count == 2
    assert store.stats.query_count == 2
    assert store.stats.hit_count == 2


@pytest.mark.asyncio
async def test_vector_search_and_cross_task_reuse(tmp_path: Path) -> None:
    embedding = FakeEmbeddingClient(dimensions=32)
    state_store = StateStore(tmp_path / "states")
    source_vector = await embedding.embed("RAG 服务响应变慢")
    source_state = state_store.save(
        task_id="task-previous",
        source_agent="reviewer",
        semantic_type="memory_embedding",
        vector=source_vector,
    )
    memory_store = SQLiteSharedMemoryStore(tmp_path / "shared.db")
    memory = memory_store.add(
        make_memory(semantic_state_id=source_state.state_id)
    )

    later_query = await embedding.embed("RAG 服务响应变慢")
    vector_hits = memory_store.search_vector(
        later_query,
        state_store,
        minimum_similarity=0.8,
    )
    topic_hits = memory_store.search_keyword("enterprise-rag")

    assert vector_hits[0].memory.memory_id == memory.memory_id
    assert vector_hits[0].score == pytest.approx(1.0)
    assert topic_hits[0].memory.memory_id == memory.memory_id
    assert memory_store.get(memory.memory_id).usage_count == 2
    assert memory.memory_id in memory_store.stats.reused_memory_ids


def test_low_confidence_memory_is_not_retrieved(tmp_path: Path) -> None:
    store = SQLiteSharedMemoryStore(
        tmp_path / "shared.db",
        confidence_threshold=0.7,
    )
    store.add(make_memory().model_copy(update={"confidence": 0.4}))

    assert store.search_keyword("enterprise-rag") == []
    assert store.search_tags(["rag"]) == []
