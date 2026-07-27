"""True non-text semantic state tests."""

from pathlib import Path

import numpy as np
import pytest

from app.llm import FakeEmbeddingClient
from app.protocol import AgentMessage, MessageAction
from app.state import StateStore, StateStoreError


@pytest.mark.asyncio
async def test_state_store_saves_and_validates_numpy_vector(tmp_path: Path) -> None:
    embedding = FakeEmbeddingClient(dimensions=24)
    vector = await embedding.embed("RAG response latency")
    store = StateStore(tmp_path / "states")

    state = store.save(
        task_id="task-1",
        source_agent="retriever",
        semantic_type="query_embedding",
        vector=vector,
        metadata={"purpose": "memory_retrieval"},
    )
    loaded = store.load(state.state_id)
    store.record_transfer(state.state_id)

    assert isinstance(loaded, np.ndarray)
    assert loaded.dtype == np.float32
    assert np.array_equal(vector, loaded)
    assert state.dimensions == 24
    assert state.byte_size == vector.nbytes
    assert Path(state.storage_ref).suffix == ".npy"
    assert not Path(state.storage_ref).is_absolute()
    assert (tmp_path / "states" / state.storage_ref).is_file()
    assert store.stats.created_count == 1
    assert store.stats.read_count == 1
    assert store.stats.transfer_count == 1
    assert store.stats.transferred_bytes == vector.nbytes


@pytest.mark.asyncio
async def test_structured_message_transfers_only_state_identifier(
    tmp_path: Path,
) -> None:
    vector = await FakeEmbeddingClient(dimensions=8).embed("semantic query")
    store = StateStore(tmp_path / "states")
    state = store.save(
        task_id="task-1",
        source_agent="retriever",
        semantic_type="query_embedding",
        vector=vector,
    )
    message = AgentMessage(
        task_id="task-1",
        sender="retriever",
        receiver="executor",
        action=MessageAction.EXECUTE_ACTION,
        semantic_state_ids=[state.state_id],
        parameters={"evidence_ref": "evidence:bundle-1"},
    )

    assert state.state_id in message.semantic_state_ids
    assert "vector" not in message.parameters
    assert str(vector.tolist()) not in message.to_json_bytes().decode("utf-8")


def test_state_store_rejects_text_and_detects_corruption(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "states")
    with pytest.raises(TypeError):
        store.save(
            task_id="task-1",
            source_agent="retriever",
            semantic_type="query_embedding",
            vector="not-a-vector",  # type: ignore[arg-type]
        )

    vector = np.asarray([0.25, 0.75], dtype=np.float32)
    state = store.save(
        task_id="task-1",
        source_agent="retriever",
        semantic_type="query_embedding",
        vector=vector,
    )
    (tmp_path / "states" / state.storage_ref).write_bytes(b"corrupted")

    with pytest.raises(StateStoreError):
        store.load(state.state_id)
