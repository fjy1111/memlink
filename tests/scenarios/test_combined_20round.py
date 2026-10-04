from pathlib import Path

import psutil

from agentipc.config import AgentIPCConfig
from agentipc.evaluation.experiment import EXPERIMENT_D
from agentipc.memory.models import MemoryType
from agentipc.memory.sqlite_store import SQLiteMemoryStore
from agentipc.providers.factory import ProviderBundle
from agentipc.providers.hash_embedding import HashEmbeddingProvider
from agentipc.providers.mock_llm import MockLLMProvider
from agentipc.scenarios.codeact_chain import run_codeact_chain
from agentipc.scenarios.knowledge_chain import run_knowledge_chain
from agentipc.scenarios.knowledge_loader import load_knowledge_documents
from agentipc.scenarios.models import (
    KnowledgeTask,
    load_codeact_tasks,
    load_knowledge_tasks,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain"
KNOWLEDGE_TASKS_PATH = KNOWLEDGE_ROOT / "tasks.json"
KNOWLEDGE_DOCUMENTS_ROOT = KNOWLEDGE_ROOT / "knowledge"
CODEACT_ROOT = PROJECT_ROOT / "tests/scenarios" / "codeact_chain"
CODEACT_TASKS_PATH = CODEACT_ROOT / "tasks.json"


def _child_pids() -> set[int]:
    return {
        child.pid
        for child in psutil.Process().children(recursive=True)
    }


def _config() -> AgentIPCConfig:
    return AgentIPCConfig(
        llm_provider="mock",
        embedding_provider="hash",
        random_seed=42,
    )


def _knowledge_provider_bundle(tasks: list[KnowledgeTask]) -> ProviderBundle:
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


def _codeact_provider_bundle() -> ProviderBundle:
    return ProviderBundle(
        llm=MockLLMProvider(default_text="deterministic codeact answer"),
        embedding=HashEmbeddingProvider(dim=64),
    )


def _assert_result_memory(work_root: Path, expected_count: int) -> None:
    store = SQLiteMemoryStore(work_root / "memory")
    try:
        records = store.list_records()
    finally:
        store.close()

    assert len(records) == expected_count
    assert all(record.memory_type is MemoryType.RESULT for record in records)


def test_combined_20_round_full_system_gate(tmp_path: Path) -> None:
    knowledge_tasks = load_knowledge_tasks(KNOWLEDGE_TASKS_PATH)
    knowledge_documents = load_knowledge_documents(KNOWLEDGE_DOCUMENTS_ROOT)
    codeact_tasks = load_codeact_tasks(CODEACT_TASKS_PATH)

    assert len(knowledge_tasks) == 10
    assert len(codeact_tasks) == 10
    assert [task.round for task in knowledge_tasks] == list(range(1, 11))
    assert [task.round for task in codeact_tasks] == list(range(1, 11))
    assert knowledge_tasks[0].group_id != codeact_tasks[0].group_id

    knowledge_work_root = tmp_path / "knowledge-10round"
    knowledge_results = run_knowledge_chain(
        tasks=knowledge_tasks,
        documents=knowledge_documents,
        work_root=knowledge_work_root,
        config=_config(),
        provider_bundle=_knowledge_provider_bundle(knowledge_tasks),
    )

    assert len(knowledge_results) == 10
    for result in knowledge_results:
        assert result.run_record.run_result.success is True
        assert result.evaluation.success is True
        assert result.run_record.experiment == EXPERIMENT_D
        assert result.run_record.use_sandbox is False
        assert result.run_record.run_result.error is None

    knowledge_round8 = knowledge_results[7]
    knowledge_round9 = knowledge_results[8]
    assert knowledge_round8.task.query == knowledge_results[1].task.query
    assert knowledge_round8.run_record.run_result.metrics["memory_retrieved"] > 0
    assert knowledge_round8.run_record.run_result.metrics["memory_used"] == 1
    assert knowledge_round8.run_record.run_result.metrics["memory_effective"] == 1
    assert knowledge_round8.run_record.run_result.metrics["memory_harmful"] == 0

    assert knowledge_round9.task.query == knowledge_results[2].task.query
    assert knowledge_round9.run_record.run_result.metrics["memory_retrieved"] > 0
    assert knowledge_round9.run_record.run_result.metrics["memory_used"] == 1
    assert knowledge_round9.run_record.run_result.metrics["memory_effective"] == 1
    assert knowledge_round9.run_record.run_result.metrics["memory_harmful"] == 0
    _assert_result_memory(knowledge_work_root, expected_count=10)

    before_child_pids = _child_pids()
    codeact_work_root = tmp_path / "codeact-10round"
    codeact_results = run_codeact_chain(
        tasks=codeact_tasks,
        fixture_root=CODEACT_ROOT,
        work_root=codeact_work_root,
        config=_config(),
        provider_bundle=_codeact_provider_bundle(),
    )
    after_child_pids = _child_pids()

    assert after_child_pids - before_child_pids == set()
    assert len(codeact_results) == 10
    assert len(knowledge_results) + len(codeact_results) == 20

    for result in codeact_results:
        assert result.run_record.run_result.success is True
        assert result.evaluation.success is True
        assert result.run_record.experiment == EXPERIMENT_D
        assert result.run_record.use_sandbox is True
        assert result.run_record.run_result.error is None

    codeact_round2 = codeact_results[1]
    codeact_round3 = codeact_results[2]
    codeact_round8 = codeact_results[7]
    codeact_round9 = codeact_results[8]

    assert codeact_round8.run_record.task == codeact_round2.run_record.task
    assert codeact_round8.run_record.task_hash == codeact_round2.run_record.task_hash
    assert codeact_round8.run_record.run_result.metrics["memory_retrieved"] > 0
    assert codeact_round8.run_record.run_result.metrics["memory_used"] == 1
    assert codeact_round8.run_record.run_result.metrics["memory_effective"] == 1
    assert codeact_round8.run_record.run_result.metrics["memory_harmful"] == 0
    assert codeact_round8.run_record.run_result.metrics["tool_call_count"] == 0
    assert codeact_round8.execution["operation"] == "identity"

    assert codeact_round9.run_record.task == codeact_round3.run_record.task
    assert codeact_round9.run_record.task_hash == codeact_round3.run_record.task_hash
    assert codeact_round9.run_record.run_result.metrics["memory_retrieved"] > 0
    assert codeact_round9.run_record.run_result.metrics["memory_used"] == 1
    assert codeact_round9.run_record.run_result.metrics["memory_effective"] == 1
    assert codeact_round9.run_record.run_result.metrics["memory_harmful"] == 0
    assert codeact_round9.run_record.run_result.metrics["tool_call_count"] == 0
    assert codeact_round9.execution["operation"] == "identity"

    for index, result in enumerate(codeact_results):
        if index not in (7, 8):
            assert result.run_record.run_result.metrics["memory_used"] == 0

    assert sum(
        result.run_record.run_result.metrics["tool_call_count"]
        for result in codeact_results
    ) == 8
    assert sum(
        result.run_record.run_result.metrics["memory_used"]
        for result in codeact_results
    ) == 2
    assert sum(
        result.run_record.run_result.metrics["memory_effective"]
        for result in codeact_results
    ) == 2
    assert sum(
        result.run_record.run_result.metrics["memory_harmful"]
        for result in codeact_results
    ) == 0
    _assert_result_memory(codeact_work_root, expected_count=10)
