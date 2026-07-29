"""Offline tests for communication and shared-memory evidence experiments."""

import csv
import json
import shutil
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.benchmark.context_scaling import ContextScalingRunner
from app.benchmark.evidence_charts import (
    CONDITION_ORDER,
    CONTEXT_EXPERIMENT_ORDER,
    CONTEXT_ORDER,
    FIGURE_NAMES,
    REQUIRED_RESULT_FILES,
    generate_evidence_figures_from_results,
    result_ref_saving_percent,
)
from app.benchmark.evidence_common import (
    build_context_task,
    repeated_fragment_bytes,
    task_semantics,
    validate_evidence_output_dir,
)
from app.benchmark.memory_reuse import MemoryReuseRunner
from app.core.config import PROJECT_ROOT
from app.llm import FakeEmbeddingClient, FakeLLMClient
from app.models import CommunicationMode, TaskCreate
from app.runtime.orchestrator import TaskOrchestrator


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json_list(value: str) -> list[str]:
    return [str(item) for item in json.loads(value)]


def test_delivery_figures_use_existing_validated_evidence_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("figure generation must not access the network")

    monkeypatch.setattr(httpx.Client, "post", forbid_network)
    monkeypatch.setattr(httpx.AsyncClient, "post", forbid_network)
    source = PROJECT_ROOT / "benchmarks" / "evidence_results"
    evidence_dir = tmp_path / "benchmarks" / "evidence_results"
    evidence_dir.mkdir(parents=True)
    for name in REQUIRED_RESULT_FILES:
        shutil.copy2(source / name, evidence_dir / name)

    protected = tmp_path / "benchmarks" / "results" / "raw_runs.jsonl"
    protected.parent.mkdir(parents=True)
    protected.write_text("preserved-300-record-results\n", encoding="utf-8")
    figures = generate_evidence_figures_from_results(evidence_dir)

    assert [path.name for path in figures] == list(FIGURE_NAMES)
    assert protected.read_text(encoding="utf-8") == (
        "preserved-300-record-results\n"
    )
    for figure in figures:
        assert figure.stat().st_size > 0
        with Image.open(figure) as image:
            assert image.size == (1600, 900)
            assert any(
                minimum < maximum
                for minimum, maximum in image.convert("RGB").getextrema()
            )


def test_delivery_figure_validation_and_percentage_are_explicit(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="directory not found"):
        generate_evidence_figures_from_results(tmp_path / "missing")

    assert CONTEXT_ORDER == ("1x", "2x", "4x", "8x")
    assert CONTEXT_EXPERIMENT_ORDER == (
        "text",
        "structured",
        "structured_no_result_ref",
    )
    assert CONDITION_ORDER == (
        "no_memory",
        "cold_memory",
        "warm_memory",
        "irrelevant_memory",
    )
    assert result_ref_saving_percent(80.0, 100.0) == pytest.approx(20.0)
    assert result_ref_saving_percent(120.0, 100.0) == pytest.approx(-20.0)
    with pytest.raises(ValueError, match="greater than zero"):
        result_ref_saving_percent(10.0, 0.0)


def test_context_generation_is_deterministic_and_semantically_equivalent() -> None:
    text, text_fragments = build_context_task(
        8,
        mode=CommunicationMode.TEXT,
    )
    structured, structured_fragments = build_context_task(
        8,
        mode=CommunicationMode.STRUCTURED,
    )
    repeated, repeated_fragments = build_context_task(
        8,
        mode=CommunicationMode.TEXT,
    )

    assert task_semantics(text) == task_semantics(structured)
    assert text_fragments == structured_fragments
    assert text.model_dump(exclude={"mode"}) == repeated.model_dump(
        exclude={"mode"}
    )
    assert text_fragments == repeated_fragments
    assert len(text_fragments) == 32
    assert len(text.prompt) <= 10_000


def test_repeated_payload_bytes_uses_exact_utf8_occurrences() -> None:
    fragments = ["证据甲", "evidence-B"]
    payloads = [
        "证据甲/evidence-B",
        "证据甲",
        "证据甲/evidence-B/evidence-B",
    ]

    expected = (
        2 * len("证据甲".encode("utf-8"))
        + 2 * len("evidence-B".encode("utf-8"))
    )
    assert repeated_fragment_bytes(payloads, fragments) == expected


def test_evidence_output_rejects_preserved_benchmark_tree() -> None:
    with pytest.raises(ValueError, match="benchmarks/results"):
        validate_evidence_output_dir(
            PROJECT_ROOT / "benchmarks" / "results"
        )
    with pytest.raises(ValueError, match="benchmarks/results"):
        validate_evidence_output_dir(
            PROJECT_ROOT / "benchmarks" / "results" / "nested"
        )


@pytest.mark.asyncio
async def test_context_experiment_is_offline_complete_and_cleans_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbid_network(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("evidence benchmark must not access the network")

    monkeypatch.setattr(httpx.AsyncClient, "post", forbid_network)
    output_dir = tmp_path / "evidence"
    temporary_root = tmp_path / "runtime"
    artifacts = await ContextScalingRunner().run(
        rounds=1,
        output_dir=output_dir,
        temporary_root=temporary_root,
    )

    assert artifacts.metadata["backend"] == "fake"
    assert artifacts.record_count == 12
    assert artifacts.task_execution_count == 12
    assert artifacts.cleanup_success
    assert list(temporary_root.iterdir()) == []
    rows = _read_csv(output_dir / "context_scaling_raw.csv")
    required = {
        "experiment",
        "context_scale",
        "round",
        "task_id",
        "success",
        "elapsed_ms",
        "message_count",
        "text_characters",
        "estimated_tokens",
        "utf8_payload_bytes",
        "json_bytes",
        "msgpack_bytes",
        "result_ref_count",
        "result_ref_payload_bytes",
        "inlined_payload_bytes",
        "repeated_payload_bytes",
        "repeated_payload_ratio",
        "semantic_state_count",
        "semantic_state_binary_bytes",
        "state_reference_bytes",
        "memory_hit_count",
    }
    assert required.issubset(rows[0])
    structured_rows = [
        row for row in rows if row["experiment"] == "structured"
    ]
    no_ref_rows = [
        row
        for row in rows
        if row["experiment"] == "structured_no_result_ref"
    ]
    text_rows = [row for row in rows if row["experiment"] == "text"]
    assert all(int(row["result_ref_count"]) == 4 for row in structured_rows)
    assert all(int(row["inlined_payload_bytes"]) == 0 for row in structured_rows)
    assert all(
        int(row["semantic_state_binary_bytes"]) == 384
        for row in structured_rows
    )
    assert all(int(row["state_reference_bytes"]) > 0 for row in structured_rows)
    assert all(int(row["inlined_payload_bytes"]) > 0 for row in no_ref_rows)
    assert all(int(row["repeated_payload_bytes"]) > 0 for row in text_rows)
    assert all(int(row["json_bytes"]) > 0 for row in rows)
    assert all(int(row["msgpack_bytes"]) > 0 for row in rows)
    assert (output_dir / "context_scaling_report.md").is_file()
    assert len(_read_csv(output_dir / "context_scaling_summary.csv")) == 12
    for figure in artifacts.figure_files:
        with Image.open(figure) as image:
            assert image.size == (1600, 900)


@pytest.mark.asyncio
async def test_memory_experiment_distinguishes_retrieval_reuse_and_isolation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbid_network(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("evidence benchmark must not access the network")

    monkeypatch.setattr(httpx.AsyncClient, "post", forbid_network)
    output_dir = tmp_path / "evidence"
    temporary_root = tmp_path / "runtime"
    artifacts = await MemoryReuseRunner().run(
        rounds=2,
        output_dir=output_dir,
        temporary_root=temporary_root,
    )

    assert artifacts.metadata["backend"] == "fake"
    assert artifacts.metadata["semantic_state_enabled"] is False
    assert artifacts.record_count == 16
    assert artifacts.task_execution_count == 24
    assert artifacts.cleanup_success
    assert list(temporary_root.iterdir()) == []
    rows = _read_csv(output_dir / "memory_reuse_raw.csv")
    required = {
        "scenario",
        "condition",
        "round",
        "task_id",
        "success",
        "elapsed_ms",
        "message_count",
        "text_characters",
        "estimated_tokens",
        "json_bytes",
        "msgpack_bytes",
        "memory_query_count",
        "memory_hit_count",
        "retrieved_memory_ids",
        "reused_memory_ids",
        "expected_memory_ids",
        "relevant_memory_reused",
        "irrelevant_memory_reused",
        "memory_reuse_precision",
        "repeated_steps",
        "avoided_steps",
        "repeated_payload_bytes",
        "reviewer_accepted",
        "reviewer_rejected_memory",
        "final_confidence",
    }
    assert required.issubset(rows[0])
    warm_rows = [row for row in rows if row["condition"] == "warm_memory"]
    assert len(warm_rows) == 4
    expected_ids: list[str] = []
    for row in warm_rows:
        retrieved = _json_list(row["retrieved_memory_ids"])
        reused = _json_list(row["reused_memory_ids"])
        expected = _json_list(row["expected_memory_ids"])
        expected_ids.extend(expected)
        assert retrieved == expected
        assert reused == expected
        assert row["relevant_memory_reused"] == "True"
        assert row["irrelevant_memory_reused"] == "False"
        assert int(row["memory_hit_count"]) == 2
    assert len(expected_ids) == len(set(expected_ids))

    irrelevant_rows = [
        row for row in rows if row["condition"] == "irrelevant_memory"
    ]
    for row in irrelevant_rows:
        assert _json_list(row["irrelevant_memory_ids"])
        assert _json_list(row["retrieved_memory_ids"]) == []
        assert _json_list(row["reused_memory_ids"]) == []
        assert row["irrelevant_memory_reused"] == "False"
    no_or_cold = [
        row
        for row in rows
        if row["condition"] in {"no_memory", "cold_memory"}
    ]
    assert all(_json_list(row["reused_memory_ids"]) == [] for row in no_or_cold)
    assert (output_dir / "memory_reuse_report.md").is_file()
    assert len(_read_csv(output_dir / "memory_reuse_summary.csv")) == 8
    for figure in artifacts.figure_files:
        with Image.open(figure) as image:
            assert image.size == (1600, 900)


@pytest.mark.asyncio
async def test_result_references_and_state_ids_resolve_real_objects(
    tmp_path: Path,
) -> None:
    orchestrator = TaskOrchestrator(
        metrics_dir=tmp_path / "metrics",
        state_dir=tmp_path / "states",
        memory_db_path=tmp_path / "memory" / "shared.db",
        llm=FakeLLMClient(),
        embedding=FakeEmbeddingClient(),
        backend_name="fake",
        enable_shared_memory=False,
        enable_semantic_state=True,
        enable_result_reference=True,
    )
    result = await orchestrator.run(
        TaskCreate(
            title="引用与状态验证",
            prompt="验证结构化协议中的结果引用和二进制状态引用可以真实解析。",
            task_topic="reference-state-test",
            mode=CommunicationMode.STRUCTURED,
        )
    )

    references = {
        str(message["result_ref"])
        for message in result.protocol_messages
        if message.get("result_ref")
    }
    result_store = getattr(orchestrator, "_result_refs")
    assert references
    assert all(reference in result_store for reference in references)
    state_ids = {
        str(state_id)
        for message in result.protocol_messages
        for state_id in message.get("semantic_state_ids", [])
    }
    assert state_ids
    for state_id in state_ids:
        vector = orchestrator.state_store.load(state_id)
        assert vector.nbytes == 128
