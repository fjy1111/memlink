"""Tests for Dashboard trace API and static evidence viewer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentipc.dashboard.app import create_app
from agentipc.evaluation.derived import DerivedMetrics
from agentipc.evaluation.env import EnvironmentSnapshot
from agentipc.evaluation.experiment import (
    EXPERIMENT_A,
    EXPERIMENT_B,
    EXPERIMENT_C,
    EXPERIMENT_D,
    ExperimentName,
)
from agentipc.evaluation.io import (
    BenchmarkSummary,
    ExperimentSummary,
    append_raw_record,
    write_summary,
)
from agentipc.evaluation.metrics import MetricsSnapshot
from agentipc.evaluation.runner import RawRunRecord
from agentipc.evaluation.trace import TraceEvent
from agentipc.protocol.refs import MemoryRef, StateRef
from agentipc.runtime.result import RunResult


RUN_ID = "20260930T120000000000Z-benchmark-smoke"
EXPERIMENTS = {
    "A": EXPERIMENT_A,
    "B": EXPERIMENT_B,
    "C": EXPERIMENT_C,
    "D": EXPERIMENT_D,
}


def _summary() -> BenchmarkSummary:
    experiments = {
        name: ExperimentSummary(
            experiment=ExperimentName(name),
            run_count=1,
            success_count=1,
            failure_count=0,
            success_rate=1.0,
            metrics={},
        )
        for name in ("A", "B", "C", "D")
    }
    derived = {
        key: DerivedMetrics(
            token_saving_rate=0.1,
            char_saving_rate=0.1,
            latency_improvement_rate=0.1,
            repeat_work_reduction_rate=None,
            effective_hit_rate=None,
        )
        for key in ("B_vs_A", "C_vs_B", "D_vs_C")
    }
    return BenchmarkSummary(
        total_records=4,
        task_count=1,
        seed_count=1,
        experiments=experiments,
        derived=derived,
    )


def _environment() -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        os_name="posix",
        platform="Linux-test",
        python_version="3.11.0",
        python_implementation="CPython",
        llm_provider="mock",
        embedding_provider="hash",
        token_method="unavailable",
        dependencies={},
    )


def _write_ready_run(root: Path, run_id: str = RUN_ID) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    write_summary(run_dir / "summary.json", _summary())
    (run_dir / "environment.json").write_text(
        json.dumps(_environment().model_dump(mode="json")), encoding="utf-8"
    )
    (run_dir / "report.md").write_text("# AgentIPC Benchmark Report\n", encoding="utf-8")
    return run_dir


def _metrics(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "message_count": 8,
        "text_chars": 400,
        "text_tokens": 100,
        "protocol_bytes": 300,
        "state_transfer_count": 1,
        "state_bytes": 256,
        "artifact_ref_count": 0,
        "memory_retrieved": 2,
        "memory_used": 1,
        "memory_effective": 1,
        "memory_harmful": 0,
        "tool_call_count": 3,
        "repeated_tool_call_count": 0,
        "llm_call_count": 4,
        "llm_prompt_tokens": 50,
        "llm_completion_tokens": 20,
        "llm_total_tokens": 70,
        "llm_usage_missing_count": 0,
        "llm_latency_ms": 12.5,
        "latency_ms": 30.0,
        "success": True,
    }
    values.update(overrides)
    return MetricsSnapshot.model_validate(values).model_dump(mode="json")


def _record(
    *,
    experiment: str = "D",
    task_id: str = "benchmark-D-task0-run0-seed42",
    trace_path: str | None,
    seed: int = 42,
) -> RawRunRecord:
    task = f"fixture task for {task_id}"
    return RawRunRecord(
        experiment=EXPERIMENTS[experiment],
        task=task,
        task_hash=hashlib.sha256(task.encode("utf-8")).hexdigest(),
        seed=seed,
        use_sandbox=False,
        run_result=RunResult(
            task_id=task_id,
            success=True,
            answer="fixture answer must not be exposed",
            error=None,
            metrics=_metrics(),
            trace_path=trace_path,
        ),
    )


def _event(
    *,
    task_id: str,
    step_id: str,
    recorded_at: float,
    action: str = "PLAN",
    state_refs: list[StateRef] | None = None,
    memory_refs: list[MemoryRef] | None = None,
) -> TraceEvent:
    return TraceEvent(
        event_type="message",
        recorded_at=recorded_at,
        trace_id="trace-fixture",
        task_id=task_id,
        message_id=f"message-{step_id}",
        step_id=step_id,
        sender="runtime",
        receiver="planner",
        message_type="REQUEST",
        action=action,
        status="OK",
        state_refs=state_refs or [],
        artifact_refs=[],
        memory_refs=memory_refs or [],
    )


def _write_trace(path: Path, events: list[TraceEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(event.model_dump_json() + "\n" for event in events),
        encoding="utf-8",
    )


def test_ready_trace_returns_validated_metrics_refs_without_paths(tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    task_id = "benchmark-D-task0-run0-seed42"
    trace_file = run_dir / "runtime" / "D-task00-run00-seed42" / "trace.jsonl"
    state_ref = StateRef(
        uri="shm://plan-vector",
        kind="plan_vector",
        shape=[64],
        dtype="<f4",
        nbytes=256,
        checksum="checksum-example",
        transport="shm",
        summary="planner state",
    )
    memory_ref = MemoryRef(
        memory_id="mem-example",
        score=1.0,
        match_type="exact_task",
        summary="cached result",
    )
    _write_trace(
        trace_file,
        [
            _event(
                task_id=task_id,
                step_id="event-1",
                recorded_at=1.0,
                state_refs=[state_ref],
                memory_refs=[memory_ref],
            )
        ],
    )
    append_raw_record(
        run_dir / "raw.jsonl",
        _record(task_id=task_id, trace_path=str(trace_file)),
    )

    response = TestClient(create_app(root)).get(f"/api/runs/{RUN_ID}/traces")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == RUN_ID
    assert len(body["traces"]) == 1
    trace = body["traces"][0]
    assert trace["task_id"] == task_id
    assert trace["experiment"] == "D"
    assert trace["seed"] == 42
    assert trace["success"] is True
    assert trace["trace_status"] == "ready"
    assert trace["reason"] is None
    assert trace["metrics"]["memory_used"] == 1
    assert trace["events"][0]["state_refs"][0]["transport"] == "shm"
    assert trace["events"][0]["state_refs"][0]["shape"] == [64]
    assert trace["events"][0]["state_refs"][0]["dtype"] == "<f4"
    assert trace["events"][0]["state_refs"][0]["nbytes"] == 256
    assert trace["events"][0]["memory_refs"][0]["memory_id"] == "mem-example"
    assert trace["events"][0]["memory_refs"][0]["match_type"] == "exact_task"
    assert "trace_path" not in response.text
    assert "fixture answer must not be exposed" not in response.text
    assert str(tmp_path) not in response.text


def test_trace_events_preserve_physical_file_order(tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    task_id = "task-D"
    trace_file = run_dir / "runtime" / "D" / "trace.jsonl"
    _write_trace(
        trace_file,
        [
            _event(task_id=task_id, step_id="event-1", recorded_at=30.0),
            _event(task_id=task_id, step_id="event-2", recorded_at=10.0, action="RETRIEVE"),
            _event(task_id=task_id, step_id="event-3", recorded_at=20.0, action="SUMMARIZE"),
        ],
    )
    append_raw_record(run_dir / "raw.jsonl", _record(task_id=task_id, trace_path="runtime/D/trace.jsonl"))

    body = TestClient(create_app(root)).get(f"/api/runs/{RUN_ID}/traces").json()

    assert [event["step_id"] for event in body["traces"][0]["events"]] == [
        "event-1",
        "event-2",
        "event-3",
    ]


def test_task_id_filter_matches_raw_record_only(tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    for experiment, task_id in [("A", "task-A"), ("D", "task-D")]:
        trace_file = run_dir / "runtime" / experiment / "trace.jsonl"
        _write_trace(trace_file, [_event(task_id=task_id, step_id=task_id, recorded_at=1.0)])
        append_raw_record(
            run_dir / "raw.jsonl",
            _record(experiment=experiment, task_id=task_id, trace_path=f"runtime/{experiment}/trace.jsonl"),
        )

    client = TestClient(create_app(root))
    response = client.get(f"/api/runs/{RUN_ID}/traces", params={"task_id": "task-D"})

    assert response.status_code == 200
    assert [item["task_id"] for item in response.json()["traces"]] == ["task-D"]
    missing = client.get(f"/api/runs/{RUN_ID}/traces", params={"task_id": "missing"})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "trace not found"}



@pytest.mark.parametrize(
    "stored_path",
    [
        f"results/{RUN_ID}/runtime/D/trace.jsonl",
        f"/old/results/{RUN_ID}/runtime/D/trace.jsonl",
        f"C:\\old\\results\\{RUN_ID}\\runtime\\D\\trace.jsonl",
    ],
)
def test_trace_path_relocates_known_run_suffix(
    tmp_path: Path, stored_path: str
) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    trace_file = run_dir / "runtime" / "D" / "trace.jsonl"
    _write_trace(
        trace_file,
        [_event(task_id="task-D", step_id="relocated", recorded_at=1.0)],
    )
    append_raw_record(
        run_dir / "raw.jsonl",
        _record(task_id="task-D", trace_path=stored_path),
    )

    trace = TestClient(create_app(root)).get(
        f"/api/runs/{RUN_ID}/traces"
    ).json()["traces"][0]

    assert trace["trace_status"] == "ready"
    assert trace["events"][0]["step_id"] == "relocated"

def test_ready_run_without_raw_jsonl_is_empty_trace_state(tmp_path: Path) -> None:
    root = tmp_path / "results"
    _write_ready_run(root)

    response = TestClient(create_app(root)).get(f"/api/runs/{RUN_ID}/traces")

    assert response.status_code == 200
    assert response.json() == {"run_id": RUN_ID, "traces": []}


def test_missing_trace_file_is_isolated_as_missing(tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    append_raw_record(
        run_dir / "raw.jsonl",
        _record(task_id="task-missing", trace_path="runtime/missing/trace.jsonl"),
    )

    trace = TestClient(create_app(root)).get(f"/api/runs/{RUN_ID}/traces").json()["traces"][0]

    assert trace["trace_status"] == "missing"
    assert trace["reason"] == "trace file missing"
    assert trace["events"] == []


def test_malformed_trace_is_invalid_without_breaking_other_trace(tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    good_file = run_dir / "runtime" / "good" / "trace.jsonl"
    bad_file = run_dir / "runtime" / "bad" / "trace.jsonl"
    _write_trace(good_file, [_event(task_id="task-good", step_id="good", recorded_at=1.0)])
    bad_file.parent.mkdir(parents=True)
    bad_file.write_text("not-json\n", encoding="utf-8")
    append_raw_record(run_dir / "raw.jsonl", _record(experiment="A", task_id="task-good", trace_path="runtime/good/trace.jsonl"))
    append_raw_record(run_dir / "raw.jsonl", _record(task_id="task-bad", trace_path="runtime/bad/trace.jsonl"))

    response = TestClient(create_app(root)).get(f"/api/runs/{RUN_ID}/traces")

    assert response.status_code == 200
    by_id = {item["task_id"]: item for item in response.json()["traces"]}
    assert by_id["task-good"]["trace_status"] == "ready"
    assert by_id["task-bad"]["trace_status"] == "invalid"
    assert by_id["task-bad"]["reason"] == "trace data invalid"
    assert by_id["task-bad"]["events"] == []


def test_malformed_raw_jsonl_returns_generic_500(tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    (run_dir / "raw.jsonl").write_text("invalid raw secret\n", encoding="utf-8")

    response = TestClient(create_app(root)).get(f"/api/runs/{RUN_ID}/traces")

    assert response.status_code == 500
    assert response.json() == {"detail": "trace repository unavailable"}
    assert str(tmp_path) not in response.text
    assert "invalid raw secret" not in response.text


def test_absolute_trace_path_outside_run_is_invalid_and_secret_is_not_read(tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    outside = tmp_path / "outside.jsonl"
    _write_trace(outside, [_event(task_id="outside-secret", step_id="outside-secret", recorded_at=1.0)])
    append_raw_record(
        run_dir / "raw.jsonl",
        _record(task_id="task-D", trace_path=str(outside)),
    )

    response = TestClient(create_app(root)).get(f"/api/runs/{RUN_ID}/traces")

    assert response.status_code == 200
    trace = response.json()["traces"][0]
    assert trace["trace_status"] == "invalid"
    assert trace["events"] == []
    assert "outside-secret" not in response.text
    assert str(outside) not in response.text


@pytest.mark.parametrize(
    "trace_path",
    [
        "../../outside.jsonl",
        f"{RUN_ID}/../../outside.jsonl",
        "C:\\outside.jsonl",
        "runtime//trace.jsonl",
    ],
)
def test_trace_path_traversal_forms_are_invalid(tmp_path: Path, trace_path: str) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    append_raw_record(run_dir / "raw.jsonl", _record(task_id="task-D", trace_path=trace_path))

    trace = TestClient(create_app(root)).get(f"/api/runs/{RUN_ID}/traces").json()["traces"][0]

    assert trace["trace_status"] == "invalid"
    assert trace["events"] == []


def test_trace_path_through_symlink_is_invalid(tmp_path: Path) -> None:
    root = tmp_path / "results"
    run_dir = _write_ready_run(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_trace(outside / "trace.jsonl", [_event(task_id="task-D", step_id="outside", recorded_at=1.0)])
    link = run_dir / "runtime" / "link"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable on this platform: {exc}")
    append_raw_record(run_dir / "raw.jsonl", _record(task_id="task-D", trace_path="runtime/link/trace.jsonl"))

    trace = TestClient(create_app(root)).get(f"/api/runs/{RUN_ID}/traces").json()["traces"][0]

    assert trace["trace_status"] == "invalid"
    assert trace["events"] == []


def test_unknown_incomplete_invalid_and_scenario_runs_are_404(tmp_path: Path) -> None:
    root = tmp_path / "results"
    incomplete_id = "20260929T120000000000Z-incomplete"
    invalid_id = "20260928T120000000000Z-benchmark-bad"
    scenario_id = "20260927T120000000000Z-scenario-knowledge"
    (root / incomplete_id).mkdir(parents=True)
    bad = _write_ready_run(root, invalid_id)
    (bad / "summary.json").write_text("{", encoding="utf-8")
    scenario = root / scenario_id
    scenario.mkdir(parents=True)
    (scenario / "scenario.json").write_text("{}", encoding="utf-8")
    (scenario / "environment.json").write_text(
        json.dumps(_environment().model_dump(mode="json")), encoding="utf-8"
    )
    (scenario / "raw.jsonl").write_text("", encoding="utf-8")

    client = TestClient(create_app(root))
    for run_id in ["unknown", incomplete_id, invalid_id, scenario_id]:
        response = client.get(f"/api/runs/{run_id}/traces")
        assert response.status_code == 404
        assert response.json() == {"detail": "run not found"}


def test_static_dashboard_files_are_served_and_root_contract_is_unchanged(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    client = TestClient(
        create_app(
            tmp_path / "results",
            static_dir=repo_root / "src" / "agentipc" / "dashboard" / "static",
        )
    )

    for path in ["/dashboard/", "/dashboard/app.js", "/dashboard/styles.css"]:
        response = client.get(path)
        assert response.status_code == 200

    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"service": "AgentIPC Dashboard", "status": "ok"}


def test_missing_static_directory_does_not_break_api(tmp_path: Path) -> None:
    client = TestClient(
        create_app(tmp_path / "results", static_dir=tmp_path / "missing-dashboard")
    )

    assert client.get("/").status_code == 200
    assert client.get("/api/runs").json() == {"runs": []}
