from pathlib import Path

import pytest

from agentipc.config import AgentIPCConfig
from agentipc.evaluation.experiment import EXPERIMENT_D
from agentipc.memory.models import MemoryType
from agentipc.memory.sqlite_store import SQLiteMemoryStore
from agentipc.providers.factory import ProviderBundle
from agentipc.providers.hash_embedding import HashEmbeddingProvider
from agentipc.providers.mock_llm import MockLLMProvider
from agentipc.scenarios.codeact_chain import run_codeact_chain
from agentipc.scenarios.models import CodeActTask, load_codeact_tasks


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CODEACT_ROOT = PROJECT_ROOT / "tests/scenarios" / "codeact_chain"
CODEACT_TASKS_PATH = CODEACT_ROOT / "tasks.json"


def _config() -> AgentIPCConfig:
    return AgentIPCConfig(
        llm_provider="mock",
        embedding_provider="hash",
        random_seed=42,
    )


def _provider_bundle() -> ProviderBundle:
    return ProviderBundle(
        llm=MockLLMProvider(default_text="deterministic codeact answer"),
        embedding=HashEmbeddingProvider(dim=64),
    )


def _real_tasks() -> list[CodeActTask]:
    return load_codeact_tasks(CODEACT_TASKS_PATH)


def _run(
    tasks: list[CodeActTask],
    *,
    fixture_root: Path,
    work_root: Path,
):
    return run_codeact_chain(
        tasks=tasks,
        fixture_root=fixture_root,
        work_root=work_root,
        config=_config(),
        provider_bundle=_provider_bundle(),
    )


def test_three_round_full_system_smoke_and_shared_memory_db(tmp_path: Path) -> None:
    tasks = _real_tasks()[:3]
    work_root = tmp_path / "codeact-smoke"

    results = _run(
        tasks,
        fixture_root=CODEACT_ROOT,
        work_root=work_root,
    )

    assert len(results) == 3
    assert [result.task.round for result in results] == [1, 2, 3]
    for result in results:
        assert result.run_record.experiment == EXPERIMENT_D
        assert result.run_record.run_result.success is True
        assert result.run_record.run_result.error is None
        assert result.evaluation.success is True
        assert result.run_record.use_sandbox is True
        assert result.run_record.run_result.metrics["state_transfer_count"] > 0
        assert result.run_record.run_result.metrics["tool_call_count"] == 1
        assert result.execution["operation"] == "codeact"

    store = SQLiteMemoryStore(work_root / "memory")
    try:
        records = store.list_records()
    finally:
        store.close()

    assert len(records) == 3
    assert all(record.memory_type is MemoryType.RESULT for record in records)


def test_empty_tasks_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tasks must not be empty"):
        _run(
            [],
            fixture_root=CODEACT_ROOT,
            work_root=tmp_path / "run",
        )


def test_mixed_group_id_rejected(tmp_path: Path) -> None:
    tasks = _real_tasks()
    mixed = [tasks[0], tasks[1].model_copy(update={"group_id": "other-group"})]

    with pytest.raises(ValueError, match="same group_id"):
        _run(
            mixed,
            fixture_root=CODEACT_ROOT,
            work_root=tmp_path / "run",
        )


def test_non_increasing_rounds_rejected(tmp_path: Path) -> None:
    tasks = _real_tasks()
    reversed_pair = [tasks[1], tasks[0]]

    with pytest.raises(ValueError, match="strictly increasing"):
        _run(
            reversed_pair,
            fixture_root=CODEACT_ROOT,
            work_root=tmp_path / "run",
        )


def test_missing_fixture_rejected(tmp_path: Path) -> None:
    task = _real_tasks()[0].model_copy(
        update={"input_artifacts": ["data/missing.txt"]}
    )

    with pytest.raises(ValueError, match="does not exist"):
        _run(
            [task],
            fixture_root=CODEACT_ROOT,
            work_root=tmp_path / "run",
        )


def test_fixture_root_escape_rejected(tmp_path: Path) -> None:
    task = _real_tasks()[0].model_copy(
        update={"input_artifacts": ["../outside.txt"]}
    )

    with pytest.raises(ValueError, match="portable relative path"):
        _run(
            [task],
            fixture_root=CODEACT_ROOT,
            work_root=tmp_path / "run",
        )


def test_wrong_config_type_rejected(tmp_path: Path) -> None:
    tasks = _real_tasks()

    with pytest.raises(TypeError, match="AgentIPCConfig"):
        run_codeact_chain(
            tasks=tasks[:1],
            fixture_root=CODEACT_ROOT,
            work_root=tmp_path / "run",
            config=object(),  # type: ignore[arg-type]
            provider_bundle=_provider_bundle(),
        )


def test_wrong_provider_bundle_type_rejected(tmp_path: Path) -> None:
    tasks = _real_tasks()

    with pytest.raises(TypeError, match="ProviderBundle"):
        run_codeact_chain(
            tasks=tasks[:1],
            fixture_root=CODEACT_ROOT,
            work_root=tmp_path / "run",
            config=_config(),
            provider_bundle=object(),  # type: ignore[arg-type]
        )


def test_work_root_existing_file_rejected(tmp_path: Path) -> None:
    work_root = tmp_path / "not-a-directory"
    work_root.write_text("file", encoding="utf-8")

    with pytest.raises(ValueError, match="work_root must be a directory path"):
        _run(
            _real_tasks()[:1],
            fixture_root=CODEACT_ROOT,
            work_root=work_root,
        )
