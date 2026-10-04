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
from agentipc.scenarios.models import load_codeact_tasks


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CODEACT_ROOT = PROJECT_ROOT / "tests/scenarios" / "codeact_chain"
CODEACT_TASKS_PATH = CODEACT_ROOT / "tasks.json"


def _child_pids() -> set[int]:
    return {
        child.pid
        for child in psutil.Process().children(recursive=True)
    }


def _provider_bundle() -> ProviderBundle:
    return ProviderBundle(
        llm=MockLLMProvider(default_text="deterministic codeact answer"),
        embedding=HashEmbeddingProvider(dim=64),
    )


def test_full_10_round_codeact_chain_stability(tmp_path: Path) -> None:
    tasks = load_codeact_tasks(CODEACT_TASKS_PATH)

    assert len(tasks) == 10
    assert [task.round for task in tasks] == list(range(1, 11))
    assert tasks[7].code == tasks[1].code
    assert tasks[7].input_artifacts == tasks[1].input_artifacts
    assert tasks[8].code == tasks[2].code
    assert tasks[8].input_artifacts == tasks[2].input_artifacts

    before_child_pids = _child_pids()
    work_root = tmp_path / "codeact-10round"
    results = run_codeact_chain(
        tasks=tasks,
        fixture_root=CODEACT_ROOT,
        work_root=work_root,
        config=AgentIPCConfig(
            llm_provider="mock",
            embedding_provider="hash",
            random_seed=42,
        ),
        provider_bundle=_provider_bundle(),
    )
    after_child_pids = _child_pids()

    assert after_child_pids - before_child_pids == set()
    assert len(results) == 10

    for result in results:
        assert result.run_record.run_result.success is True
        assert result.evaluation.success is True
        assert result.run_record.run_result.error is None
        assert result.run_record.experiment == EXPERIMENT_D
        assert result.run_record.use_sandbox is True

    round2 = results[1]
    round3 = results[2]
    round8 = results[7]
    round9 = results[8]

    assert round2.run_record.run_result.metrics["tool_call_count"] == 1
    assert round2.execution["operation"] == "codeact"
    assert round2.evaluation.success is True

    assert round3.run_record.run_result.metrics["tool_call_count"] == 1
    assert round3.execution["operation"] == "codeact"
    assert round3.evaluation.success is True

    assert round8.run_record.task == round2.run_record.task
    assert round8.run_record.task_hash == round2.run_record.task_hash
    assert round8.run_record.run_result.metrics["memory_retrieved"] > 0
    assert round8.run_record.run_result.metrics["memory_used"] == 1
    assert round8.run_record.run_result.metrics["memory_effective"] == 1
    assert round8.run_record.run_result.metrics["memory_harmful"] == 0
    assert round8.run_record.run_result.metrics["tool_call_count"] == 0
    assert round8.execution["operation"] == "identity"
    assert round8.evaluation.success is True

    assert round9.run_record.task == round3.run_record.task
    assert round9.run_record.task_hash == round3.run_record.task_hash
    assert round9.run_record.run_result.metrics["memory_retrieved"] > 0
    assert round9.run_record.run_result.metrics["memory_used"] == 1
    assert round9.run_record.run_result.metrics["memory_effective"] == 1
    assert round9.run_record.run_result.metrics["memory_harmful"] == 0
    assert round9.run_record.run_result.metrics["tool_call_count"] == 0
    assert round9.execution["operation"] == "identity"
    assert round9.evaluation.success is True

    for index, result in enumerate(results):
        if index not in (7, 8):
            assert result.run_record.run_result.metrics["memory_used"] == 0

    assert sum(
        result.run_record.run_result.metrics["tool_call_count"]
        for result in results
    ) == 8
    assert sum(
        result.run_record.run_result.metrics["memory_used"]
        for result in results
    ) == 2
    assert sum(
        result.run_record.run_result.metrics["memory_effective"]
        for result in results
    ) == 2
    assert sum(
        result.run_record.run_result.metrics["memory_harmful"]
        for result in results
    ) == 0

    store = SQLiteMemoryStore(work_root / "memory")
    try:
        records = store.list_records()
    finally:
        store.close()

    assert len(records) == 10
    assert all(record.memory_type is MemoryType.RESULT for record in records)
