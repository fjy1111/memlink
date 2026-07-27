"""SQLite-backed cross-task shared memory with three retrieval strategies."""

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from app.core.logging import get_logger
from app.memory.models import (
    MemorySearchHit,
    MemoryStoreStats,
    MemoryType,
    SharedMemory,
)
from app.models.domain import utc_now
from app.state import StateStore, StateStoreError

logger = get_logger(__name__)


class MemoryStoreError(RuntimeError):
    """Raised when persistent memory cannot be read or written."""


class SQLiteSharedMemoryStore:
    """Simple, deterministic SQLite repository for reusable memories."""

    def __init__(
        self,
        database_path: Path,
        *,
        confidence_threshold: float = 0.5,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self._database_path = database_path
        self._confidence_threshold = confidence_threshold
        self._lock = threading.RLock()
        self._stats = MemoryStoreStats()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def stats(self) -> MemoryStoreStats:
        """Return an isolated copy of query counters."""

        with self._lock:
            return self._stats.model_copy(deep=True)

    def count(self) -> int:
        """Return the number of persisted shared-memory records."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS record_count FROM memories"
            ).fetchone()
        return int(row["record_count"]) if row is not None else 0

    def add(self, memory: SharedMemory) -> SharedMemory:
        """Insert a memory or merge a content-identical duplicate."""

        content_hash = self._content_hash(memory)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM memories WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if existing is not None:
                current = self._row_to_memory(existing)
                merged_tags = sorted(set(current.tags).union(memory.tags))
                merged_evidence = sorted(
                    set(current.evidence_ids).union(memory.evidence_ids)
                )
                updated_at = utc_now()
                connection.execute(
                    """
                    UPDATE memories
                    SET tags_json = ?, evidence_ids_json = ?, confidence = ?,
                        semantic_state_id = COALESCE(semantic_state_id, ?),
                        updated_at = ?
                    WHERE memory_id = ?
                    """,
                    (
                        json.dumps(merged_tags, ensure_ascii=False),
                        json.dumps(merged_evidence, ensure_ascii=False),
                        max(current.confidence, memory.confidence),
                        memory.semantic_state_id,
                        updated_at.isoformat(),
                        current.memory_id,
                    ),
                )
                logger.info("Merged duplicate shared memory %s", current.memory_id)
                return self.get(current.memory_id)

            connection.execute(
                """
                INSERT INTO memories (
                    memory_id, task_topic, source_agent, memory_type, summary,
                    content, tags_json, evidence_ids_json, semantic_state_id,
                    confidence, usage_count, content_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.memory_id,
                    memory.task_topic,
                    memory.source_agent,
                    memory.memory_type.value,
                    memory.summary,
                    memory.content,
                    json.dumps(memory.tags, ensure_ascii=False),
                    json.dumps(memory.evidence_ids, ensure_ascii=False),
                    memory.semantic_state_id,
                    memory.confidence,
                    memory.usage_count,
                    content_hash,
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                ),
            )
        logger.info("Stored shared memory %s", memory.memory_id)
        return memory.model_copy(deep=True)

    def get(self, memory_id: str) -> SharedMemory:
        """Fetch a single memory without counting it as a search hit."""

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            raise MemoryStoreError(f"Shared memory {memory_id!r} was not found")
        return self._row_to_memory(row)

    def search_keyword(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[MemorySearchHit]:
        """Search topic, summary, and content with a parameterized LIKE query."""

        if not query.strip():
            return []
        pattern = f"%{query.strip().lower()}%"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memories
                WHERE confidence >= ?
                  AND (
                    lower(task_topic) LIKE ?
                    OR lower(summary) LIKE ?
                    OR lower(content) LIKE ?
                  )
                ORDER BY confidence DESC, updated_at DESC
                LIMIT ?
                """,
                (
                    self._confidence_threshold,
                    pattern,
                    pattern,
                    pattern,
                    limit,
                ),
            ).fetchall()
        hits = [
            MemorySearchHit(
                memory=self._row_to_memory(row),
                score=1.0 if row["task_topic"].lower() == query.strip().lower() else 0.8,
                match_type="keyword",
            )
            for row in rows
        ]
        self._record_query(hits)
        return hits

    def search_tags(
        self,
        tags: list[str],
        *,
        limit: int = 5,
    ) -> list[MemorySearchHit]:
        """Match normalized tags without relying on SQLite JSON extensions."""

        wanted = {tag.strip().lower() for tag in tags if tag.strip()}
        if not wanted:
            return []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memories
                WHERE confidence >= ?
                ORDER BY confidence DESC, updated_at DESC
                """,
                (self._confidence_threshold,),
            ).fetchall()
        hits: list[MemorySearchHit] = []
        for row in rows:
            memory = self._row_to_memory(row)
            existing = {tag.lower() for tag in memory.tags}
            overlap = wanted.intersection(existing)
            if overlap:
                hits.append(
                    MemorySearchHit(
                        memory=memory,
                        score=len(overlap) / len(wanted),
                        match_type="tag",
                    )
                )
        hits.sort(key=lambda hit: (hit.score, hit.memory.confidence), reverse=True)
        selected = hits[:limit]
        self._record_query(selected)
        return selected

    def search_vector(
        self,
        query_vector: npt.NDArray[np.floating[Any]],
        state_store: StateStore,
        *,
        limit: int = 5,
        minimum_similarity: float = 0.0,
    ) -> list[MemorySearchHit]:
        """Rank memories by cosine similarity to stored semantic states."""

        if not isinstance(query_vector, np.ndarray) or query_vector.ndim != 1:
            raise ValueError("query_vector must be a one-dimensional NumPy array")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memories
                WHERE confidence >= ? AND semantic_state_id IS NOT NULL
                """,
                (self._confidence_threshold,),
            ).fetchall()
        hits: list[MemorySearchHit] = []
        for row in rows:
            memory = self._row_to_memory(row)
            if memory.semantic_state_id is None:
                continue
            try:
                candidate = state_store.load(memory.semantic_state_id)
            except StateStoreError:
                logger.warning(
                    "Skipping memory %s with unavailable semantic state",
                    memory.memory_id,
                )
                continue
            if candidate.shape != query_vector.shape:
                continue
            similarity = self._cosine_similarity(query_vector, candidate)
            if similarity >= minimum_similarity:
                hits.append(
                    MemorySearchHit(
                        memory=memory,
                        score=max(0.0, min(1.0, (similarity + 1.0) / 2.0)),
                        match_type="vector",
                    )
                )
        hits.sort(key=lambda hit: (hit.score, hit.memory.confidence), reverse=True)
        selected = hits[:limit]
        self._record_query(selected)
        return selected

    def _initialize(self) -> None:
        """Create portable schema and indexes."""

        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        memory_id TEXT PRIMARY KEY,
                        task_topic TEXT NOT NULL,
                        source_agent TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        content TEXT NOT NULL,
                        tags_json TEXT NOT NULL,
                        evidence_ids_json TEXT NOT NULL,
                        semantic_state_id TEXT,
                        confidence REAL NOT NULL,
                        usage_count INTEGER NOT NULL DEFAULT 0,
                        content_hash TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_memories_topic
                        ON memories(task_topic);
                    CREATE INDEX IF NOT EXISTS idx_memories_confidence
                        ON memories(confidence);
                    """
                )
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Unable to initialize shared memory: {exc}") from exc

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection that is always committed and closed."""

        connection = sqlite3.connect(self._database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise MemoryStoreError(f"SQLite shared-memory operation failed: {exc}") from exc
        finally:
            connection.close()

    def _record_query(self, hits: list[MemorySearchHit]) -> None:
        """Count real hits and update usage for returned memories."""

        with self._lock:
            self._stats.query_count += 1
            if not hits:
                return
            self._stats.query_hit_count += 1
            ids = [hit.memory.memory_id for hit in hits]
            self._stats.hit_count += len(ids)
            for memory_id in ids:
                if memory_id not in self._stats.reused_memory_ids:
                    self._stats.reused_memory_ids.append(memory_id)
            placeholders = ",".join("?" for _ in ids)
            with self._connect() as connection:
                connection.execute(
                    f"""
                    UPDATE memories
                    SET usage_count = usage_count + 1, updated_at = ?
                    WHERE memory_id IN ({placeholders})
                    """,
                    (utc_now().isoformat(), *ids),
                )
        for hit in hits:
            hit.memory.usage_count += 1

    @staticmethod
    def _content_hash(memory: SharedMemory) -> str:
        payload = "\0".join(
            (
                memory.task_topic.strip().lower(),
                memory.memory_type.value,
                memory.summary.strip(),
                memory.content.strip(),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _cosine_similarity(
        left: npt.NDArray[np.floating[Any]],
        right: npt.NDArray[np.floating[Any]],
    ) -> float:
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator == 0.0:
            return 0.0
        return float(np.dot(left, right) / denominator)

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> SharedMemory:
        return SharedMemory(
            memory_id=row["memory_id"],
            task_topic=row["task_topic"],
            source_agent=row["source_agent"],
            memory_type=MemoryType(row["memory_type"]),
            summary=row["summary"],
            content=row["content"],
            tags=json.loads(row["tags_json"]),
            evidence_ids=json.loads(row["evidence_ids_json"]),
            semantic_state_id=row["semantic_state_id"],
            confidence=float(row["confidence"]),
            usage_count=int(row["usage_count"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
