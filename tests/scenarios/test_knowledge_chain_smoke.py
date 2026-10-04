from pathlib import Path

import pytest

from agentipc.config import AgentIPCConfig
from agentipc.evaluation.experiment import EXPERIMENT_D
from agentipc.memory.sqlite_store import SQLiteMemoryStore
from agentipc.providers.factory import ProviderBundle
from agentipc.providers.hash_embedding import HashEmbeddingProvider
from agentipc.providers.mock_llm import MockLLMProvider
from agentipc.scenarios.knowledge_chain import run_knowledge_chain
from agentipc.scenarios.knowledge_loader import (
    KnowledgeDocument,
    load_knowledge_documents,
)
from agentipc.scenarios.models import KnowledgeTask, load_knowledge_tasks


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_TASKS_PATH = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain" / "tasks.json"
REAL_KNOWLEDGE_ROOT = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain" / "knowledge"


def _config() -> AgentIPCConfig:
    return AgentIPCConfig(
        llm_provider="mock",
        embedding_provider="hash",
        random_seed=42,
    )


def _provider_bundle(tasks: list[KnowledgeTask]) -> ProviderBundle:
    keyword_responses: dict[str, str] = {}
    for task in tasks:
        answer = "；".join(task.expected.answer_contains)
        if task.query in keyword_responses:
            assert keyword_responses[task.query] == answer
        else:
            keyword_responses[task.query] = answer

    return ProviderBundle(
        llm=MockLLMProvider(keyword_responses=keyword_responses),
        embedding=HashEmbeddingProvider(dim=64),
    )


def _real_inputs() -> tuple[list[KnowledgeTask], list[KnowledgeDocument]]:
    return (
        load_knowledge_tasks(REAL_TASKS_PATH),
        load_knowledge_documents(REAL_KNOWLEDGE_ROOT),
    )


def test_three_round_full_system_smoke_and_shared_memory_db(tmp_path: Path) -> None:
    all_tasks, documents = _real_inputs()
    tasks = all_tasks[:3]
    work_root = tmp_path / "knowledge-smoke"

    results = run_knowledge_chain(
        tasks=tasks,
        documents=documents,
        work_root=work_root,
        config=_config(),
        provider_bundle=_provider_bundle(tasks),
    )

    assert len(results) == 3
    assert [result.task.round for result in results] == [1, 2, 3]
    for result in results:
        assert result.run_record.experiment == EXPERIMENT_D
        assert result.run_record.run_result.success is True
        assert result.evaluation.success is True
        assert result.run_record.use_sandbox is False
        assert result.run_record.run_result.metrics["state_transfer_count"] > 0

    store = SQLiteMemoryStore(work_root / "memory")
    try:
        records = store.list_records()
    finally:
        store.close()

    assert len(records) == 3
    assert [record.task_topic for record in records] == [
        task.query for task in tasks
    ]


def test_empty_tasks_rejected(tmp_path: Path) -> None:
    tasks, documents = _real_inputs()
    with pytest.raises(ValueError, match="tasks must not be empty"):
        run_knowledge_chain(
            tasks=[],
            documents=documents,
            work_root=tmp_path / "run",
            config=_config(),
            provider_bundle=_provider_bundle(tasks),
        )


def test_empty_documents_rejected(tmp_path: Path) -> None:
    tasks, _ = _real_inputs()
    with pytest.raises(ValueError, match="documents must not be empty"):
        run_knowledge_chain(
            tasks=tasks[:1],
            documents=[],
            work_root=tmp_path / "run",
            config=_config(),
            provider_bundle=_provider_bundle(tasks[:1]),
        )


def test_mixed_group_id_rejected(tmp_path: Path) -> None:
    tasks, documents = _real_inputs()
    mixed = [tasks[0], tasks[1].model_copy(update={"group_id": "other-group"})]

    with pytest.raises(ValueError, match="same group_id"):
        run_knowledge_chain(
            tasks=mixed,
            documents=documents,
            work_root=tmp_path / "run",
            config=_config(),
            provider_bundle=_provider_bundle(mixed),
        )


def test_non_increasing_rounds_rejected(tmp_path: Path) -> None:
    tasks, documents = _real_inputs()
    reversed_pair = [tasks[1], tasks[0]]

    with pytest.raises(ValueError, match="strictly increasing"):
        run_knowledge_chain(
            tasks=reversed_pair,
            documents=documents,
            work_root=tmp_path / "run",
            config=_config(),
            provider_bundle=_provider_bundle(reversed_pair),
        )


def test_duplicate_document_id_rejected(tmp_path: Path) -> None:
    tasks, documents = _real_inputs()

    with pytest.raises(ValueError, match="document_id values must be unique"):
        run_knowledge_chain(
            tasks=tasks[:1],
            documents=[*documents, documents[0]],
            work_root=tmp_path / "run",
            config=_config(),
            provider_bundle=_provider_bundle(tasks[:1]),
        )


def test_missing_expected_evidence_document_rejected(tmp_path: Path) -> None:
    tasks, documents = _real_inputs()
    expected = tasks[0].expected.model_copy(
        update={"evidence_ids": ["missing-document"]}
    )
    bad_task = tasks[0].model_copy(update={"expected": expected})

    with pytest.raises(ValueError, match="missing documents"):
        run_knowledge_chain(
            tasks=[bad_task],
            documents=documents,
            work_root=tmp_path / "run",
            config=_config(),
            provider_bundle=_provider_bundle([bad_task]),
        )


def test_wrong_config_type_rejected(tmp_path: Path) -> None:
    tasks, documents = _real_inputs()

    with pytest.raises(TypeError, match="AgentIPCConfig"):
        run_knowledge_chain(
            tasks=tasks[:1],
            documents=documents,
            work_root=tmp_path / "run",
            config=object(),  # type: ignore[arg-type]
            provider_bundle=_provider_bundle(tasks[:1]),
        )


def test_wrong_provider_bundle_type_rejected(tmp_path: Path) -> None:
    tasks, documents = _real_inputs()

    with pytest.raises(TypeError, match="ProviderBundle"):
        run_knowledge_chain(
            tasks=tasks[:1],
            documents=documents,
            work_root=tmp_path / "run",
            config=_config(),
            provider_bundle=object(),  # type: ignore[arg-type]
        )


def test_work_root_existing_file_rejected(tmp_path: Path) -> None:
    tasks, documents = _real_inputs()
    work_root = tmp_path / "not-a-directory"
    work_root.write_text("file", encoding="utf-8")

    with pytest.raises(ValueError, match="work_root must be a directory path"):
        run_knowledge_chain(
            tasks=tasks[:1],
            documents=documents,
            work_root=work_root,
            config=_config(),
            provider_bundle=_provider_bundle(tasks[:1]),
        )
