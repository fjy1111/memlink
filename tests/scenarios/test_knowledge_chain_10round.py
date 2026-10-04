from pathlib import Path

from agentipc.config import AgentIPCConfig
from agentipc.evaluation.experiment import EXPERIMENT_D
from agentipc.memory.models import MemoryType
from agentipc.memory.sqlite_store import SQLiteMemoryStore
from agentipc.providers.factory import ProviderBundle
from agentipc.providers.hash_embedding import HashEmbeddingProvider
from agentipc.providers.mock_llm import MockLLMProvider
from agentipc.scenarios.knowledge_chain import run_knowledge_chain
from agentipc.scenarios.knowledge_loader import load_knowledge_documents
from agentipc.scenarios.models import KnowledgeTask, load_knowledge_tasks


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_TASKS_PATH = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain" / "tasks.json"
REAL_KNOWLEDGE_ROOT = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain" / "knowledge"


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


def test_full_10_round_knowledge_chain(tmp_path: Path) -> None:
    tasks = load_knowledge_tasks(REAL_TASKS_PATH)
    documents = load_knowledge_documents(REAL_KNOWLEDGE_ROOT)

    assert len(tasks) == 10
    assert [task.round for task in tasks] == list(range(1, 11))
    assert len(documents) == 4
    assert tasks[7].query == tasks[1].query
    assert tasks[8].query == tasks[2].query

    work_root = tmp_path / "knowledge-10round"
    results = run_knowledge_chain(
        tasks=tasks,
        documents=documents,
        work_root=work_root,
        config=AgentIPCConfig(
            llm_provider="mock",
            embedding_provider="hash",
            random_seed=42,
        ),
        provider_bundle=_provider_bundle(tasks),
    )

    assert len(results) == 10
    for result in results:
        assert result.run_record.run_result.success is True
        assert result.evaluation.success is True
        assert result.run_record.experiment == EXPERIMENT_D
        assert result.run_record.use_sandbox is False
        assert result.run_record.run_result.error is None

    assert sum(
        result.run_record.run_result.metrics["memory_retrieved"]
        for result in results
    ) > 0

    round8 = results[7]
    round9 = results[8]

    assert round8.task.query == results[1].task.query
    assert round8.run_record.run_result.metrics["memory_retrieved"] > 0
    assert round8.run_record.run_result.metrics["memory_used"] == 1
    assert round8.run_record.run_result.metrics["memory_effective"] == 1
    assert round8.run_record.run_result.metrics["memory_harmful"] == 0

    assert round9.task.query == results[2].task.query
    assert round9.run_record.run_result.metrics["memory_retrieved"] > 0
    assert round9.run_record.run_result.metrics["memory_used"] == 1
    assert round9.run_record.run_result.metrics["memory_effective"] == 1
    assert round9.run_record.run_result.metrics["memory_harmful"] == 0

    store = SQLiteMemoryStore(work_root / "memory")
    try:
        records = store.list_records()
    finally:
        store.close()

    assert len(records) == 10
    assert all(record.memory_type is MemoryType.RESULT for record in records)
