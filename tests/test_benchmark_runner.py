"""Real offline benchmark matrix, isolation, ablation, and stability tests."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.benchmark import BenchmarkConfig, ExperimentName
from app.benchmark.matrix import EXPERIMENT_MATRIX, select_experiments
from app.benchmark.runner import BenchmarkRunner
from app.core.config import Settings


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        metrics_dir=tmp_path / "unused-metrics",
        state_dir=tmp_path / "unused-states",
        memory_db_path=tmp_path / "unused-memory.db",
        llm_backend="fake",
        embedding_backend="fake",
    )


def test_formal_matrix_contains_five_real_configurations() -> None:
    assert [item.name for item in EXPERIMENT_MATRIX] == [
        ExperimentName.TEXT,
        ExperimentName.STRUCTURED,
        ExperimentName.STRUCTURED_NO_MEMORY,
        ExperimentName.STRUCTURED_NO_SEMANTIC_STATE,
        ExperimentName.STRUCTURED_NO_RESULT_REF,
    ]
    assert len(select_experiments("ablation")) == 5
    with pytest.raises(ValueError):
        select_experiments("not-real")


def test_benchmark_rejects_any_real_network_backend(tmp_path: Path) -> None:
    settings = build_settings(tmp_path).model_copy(
        update={
            "llm_backend": "deepseek",
            "deepseek_api_key": "test-only-secret",
            "deepseek_base_url": "https://example.invalid/v1",
            "deepseek_model": "test-model",
        }
    )

    with pytest.raises(ValueError, match="仅允许使用离线 Fake"):
        BenchmarkRunner(settings=settings)


@pytest.mark.asyncio
async def test_runner_isolates_experiments_and_executes_real_ablations(
    tmp_path: Path,
) -> None:
    temporary_root = tmp_path / "runtime"
    results_dir = tmp_path / "results"
    runner = BenchmarkRunner(settings=build_settings(tmp_path))

    artifacts = await runner.run(
        BenchmarkConfig(
            rounds=1,
            seed=42,
            results_dir=results_dir,
            temporary_root=temporary_root,
            experiment="all",
        )
    )

    counts = Counter(record.experiment_name for record in artifacts.records)
    assert counts == {name: 6 for name in ExperimentName}
    assert all(record.success for record in artifacts.records)
    for experiment in ExperimentName:
        first = next(
            record
            for record in artifacts.records
            if record.experiment_name is experiment
        )
        assert first.sqlite_record_count_before == 0
        assert first.semantic_state_file_count_before == 0

    text = [
        record
        for record in artifacts.records
        if record.experiment_name is ExperimentName.TEXT
    ]
    assert all(record.protocol_message_count == 0 for record in text)
    assert all(record.msgpack_serialized_bytes == 0 for record in text)

    no_memory = [
        record
        for record in artifacts.records
        if record.experiment_name is ExperimentName.STRUCTURED_NO_MEMORY
    ]
    assert all(record.memory_query_count == 0 for record in no_memory)
    assert all(record.memory_hit_count == 0 for record in no_memory)
    assert all(record.sqlite_record_count_after == 0 for record in no_memory)

    no_state = [
        record
        for record in artifacts.records
        if record.experiment_name
        is ExperimentName.STRUCTURED_NO_SEMANTIC_STATE
    ]
    assert all(record.semantic_state_transfer_count == 0 for record in no_state)
    assert all(record.semantic_state_file_count_after == 0 for record in no_state)

    structured = [
        record
        for record in artifacts.records
        if record.experiment_name is ExperimentName.STRUCTURED
    ]
    no_reference = [
        record
        for record in artifacts.records
        if record.experiment_name is ExperimentName.STRUCTURED_NO_RESULT_REF
    ]
    assert all(record.result_reference_count > 0 for record in structured)
    assert all(record.full_result_transfer_count == 0 for record in structured)
    assert all(record.result_reference_count == 0 for record in no_reference)
    assert all(record.full_result_transfer_count > 0 for record in no_reference)
    assert sum(record.json_serialized_bytes for record in no_reference) > sum(
        record.json_serialized_bytes for record in structured
    )

    assert artifacts.stability is not None
    assert artifacts.stability.total_tasks == 6
    assert artifacts.stability.successful_tasks == 6
    assert artifacts.stability.cleanup_success is True
    assert artifacts.stability.database_handle_released is True
    assert not list(temporary_root.iterdir())
    assert set(artifacts.output_files) == {
        "raw_jsonl",
        "raw_csv",
        "summary_csv",
        "summary_json",
        "ablation_csv",
        "stability_json",
        "environment_json",
        "report",
    }
    assert all(path.is_file() for path in artifacts.output_files.values())
    raw_lines = (
        artifacts.output_files["raw_jsonl"]
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(raw_lines) == 30
    assert all(json.loads(line)["run_id"] for line in raw_lines)


class FailingLLM:
    """Offline test double proving failures are recorded, not converted."""

    retry_count = 0

    async def generate(self, **kwargs: Any) -> str:
        del kwargs
        raise RuntimeError("intentional offline failure")


@pytest.mark.asyncio
async def test_runner_persists_failed_runs_truthfully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.benchmark.runner.create_llm_client",
        lambda settings: FailingLLM(),
    )
    runner = BenchmarkRunner(settings=build_settings(tmp_path))

    artifacts = await runner.run(
        BenchmarkConfig(
            rounds=1,
            results_dir=tmp_path / "failed-results",
            experiment="text",
        )
    )

    assert len(artifacts.records) == 6
    assert all(not record.success for record in artifacts.records)
    assert all(record.error_count == 1 for record in artifacts.records)
    assert all("intentional offline failure" in record.error_message for record in artifacts.records)
    assert artifacts.summaries[0].completion_rate == 0.0
    assert artifacts.summaries[0].error_rate == 1.0
