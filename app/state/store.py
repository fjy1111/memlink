"""Cross-platform binary NumPy state store."""

import hashlib
import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import numpy.typing as npt

from app.core.logging import get_logger
from app.state.models import SemanticState, StateStoreStats

logger = get_logger(__name__)


class StateStoreError(RuntimeError):
    """Raised when semantic state is missing or fails integrity checks."""


class StateStore:
    """Persist vectors as binary ``.npy`` files and validate every read."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, SemanticState] = {}
        self._stats = StateStoreStats()
        self._lock = threading.RLock()
        self._load_metadata()

    @property
    def stats(self) -> StateStoreStats:
        """Return an immutable snapshot of state access counters."""

        with self._lock:
            return self._stats.model_copy(deep=True)

    def file_count(self) -> int:
        """Return the number of complete vector/metadata state pairs."""

        with self._lock:
            return sum(
                1
                for state in self._states.values()
                if self._resolve_storage_path(state.storage_ref).is_file()
            )

    def save(
        self,
        *,
        task_id: str,
        source_agent: str,
        semantic_type: str,
        vector: npt.NDArray[np.floating[Any]],
        metadata: dict[str, Any] | None = None,
    ) -> SemanticState:
        """Save one numeric vector without converting it to natural language."""

        if not isinstance(vector, np.ndarray):
            raise TypeError("Semantic state vector must be a NumPy ndarray")
        if vector.ndim != 1 or vector.size == 0:
            raise ValueError("Semantic state vector must be non-empty and one-dimensional")
        if not np.issubdtype(vector.dtype, np.floating):
            raise ValueError("Semantic state vector must use a floating-point dtype")

        normalized = np.ascontiguousarray(vector)
        vector_bytes = normalized.tobytes(order="C")
        content_hash = hashlib.sha256(vector_bytes).hexdigest()
        state_id = str(uuid4())
        vector_path = self._root_dir / f"{state_id}.npy"
        metadata_path = self._root_dir / f"{state_id}.json"
        temporary_vector = vector_path.with_suffix(".npy.tmp")
        temporary_metadata = metadata_path.with_suffix(".json.tmp")

        state = SemanticState(
            state_id=state_id,
            task_id=task_id,
            source_agent=source_agent,
            semantic_type=semantic_type,
            dimensions=int(normalized.size),
            dtype=str(normalized.dtype),
            byte_size=len(vector_bytes),
            storage_ref=vector_path.name,
            content_hash=content_hash,
            metadata=metadata or {},
        )
        try:
            with temporary_vector.open("wb") as file_handle:
                np.save(file_handle, normalized, allow_pickle=False)
            temporary_vector.replace(vector_path)
            temporary_metadata.write_text(
                state.model_dump_json(indent=2),
                encoding="utf-8",
            )
            temporary_metadata.replace(metadata_path)
        except OSError as exc:
            logger.exception("Unable to save semantic state %s", state_id)
            raise StateStoreError(f"Unable to save semantic state: {exc}") from exc

        with self._lock:
            self._states[state_id] = state
            self._stats.created_count += 1
        logger.info(
            "Saved semantic state %s (%d bytes)",
            state_id,
            state.byte_size,
        )
        return state.model_copy(deep=True)

    def get_metadata(self, state_id: str) -> SemanticState:
        """Return metadata without reading or transferring vector bytes."""

        with self._lock:
            try:
                return self._states[state_id].model_copy(deep=True)
            except KeyError as exc:
                raise StateStoreError(
                    f"Semantic state {state_id!r} was not found"
                ) from exc

    def load(self, state_id: str) -> npt.NDArray[np.floating[Any]]:
        """Load and validate vector dimensions, dtype, size, and hash."""

        state = self.get_metadata(state_id)
        path = self._resolve_storage_path(state.storage_ref)
        try:
            vector = np.load(path, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise StateStoreError(f"Unable to read semantic state {state_id}: {exc}") from exc
        if vector.ndim != 1 or vector.size != state.dimensions:
            raise StateStoreError(f"Semantic state {state_id} dimension mismatch")
        if str(vector.dtype) != state.dtype:
            raise StateStoreError(f"Semantic state {state_id} dtype mismatch")
        payload = np.ascontiguousarray(vector).tobytes(order="C")
        if len(payload) != state.byte_size:
            raise StateStoreError(f"Semantic state {state_id} byte-size mismatch")
        if hashlib.sha256(payload).hexdigest() != state.content_hash:
            raise StateStoreError(f"Semantic state {state_id} hash mismatch")
        with self._lock:
            self._stats.read_count += 1
        return vector

    def record_transfer(self, state_id: str) -> None:
        """Record one state-ID handoff and its referenced binary size."""

        state = self.get_metadata(state_id)
        with self._lock:
            self._stats.transfer_count += 1
            self._stats.transferred_bytes += state.byte_size

    def _load_metadata(self) -> None:
        """Restore metadata index for vectors persisted by an earlier run."""

        for metadata_path in self._root_dir.glob("*.json"):
            try:
                state = SemanticState.model_validate_json(
                    metadata_path.read_text(encoding="utf-8")
                )
                if self._resolve_storage_path(state.storage_ref).is_file():
                    self._states[state.state_id] = state
            except (OSError, ValueError):
                logger.warning("Ignoring invalid state metadata %s", metadata_path)

    def _resolve_storage_path(self, storage_ref: str) -> Path:
        """Resolve persisted relative references inside the configured store."""

        candidate = Path(storage_ref)
        return candidate if candidate.is_absolute() else self._root_dir / candidate
