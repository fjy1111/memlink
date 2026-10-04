from pathlib import Path
import socket

import pytest
from fastapi.testclient import TestClient

from agentipc.cli import main
from agentipc.dashboard.app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _fail_connect(*args: object, **kwargs: object) -> None:
    raise AssertionError("dashboard regression must remain fully offline")


def _only_result_dir(results_root: Path) -> Path:
    children = [path for path in results_root.iterdir() if path.is_dir()]
    assert len(children) == 1
    result_dir = children[0]
    assert result_dir.name.endswith("-benchmark-smoke")
    return result_dir


def test_dashboard_final_regression_uses_real_mock_benchmark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket.socket, "connect", _fail_connect)
    results_root = tmp_path / "results"

    exit_code = main(
        [
            "benchmark",
            "--suite",
            "smoke",
            "--repeat",
            "1",
            "--seed",
            "42",
            "--provider",
            "mock",
            "--results-root",
            str(results_root),
        ]
    )

    assert exit_code == 0
    result_dir = _only_result_dir(results_root)
    run_id = result_dir.name

    client = TestClient(
        create_app(
            results_root,
            static_dir=PROJECT_ROOT / "src" / "agentipc" / "dashboard" / "static",
        )
    )

    root_response = client.get("/")
    assert root_response.status_code == 200
    assert root_response.json() == {
        "service": "AgentIPC Dashboard",
        "status": "ok",
    }

    runs_response = client.get("/api/runs")
    assert runs_response.status_code == 200
    runs = runs_response.json()["runs"]
    ready = [run for run in runs if run["status"] == "ready"]
    assert len(ready) == 1
    assert ready[0]["run_id"] == run_id
    assert ready[0]["llm_provider"] == "mock"
    assert ready[0]["embedding_provider"] == "hash"
    assert ready[0]["total_records"] == 4
    assert ready[0]["task_count"] == 1
    assert ready[0]["seed_count"] == 1

    detail_response = client.get(f"/api/runs/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert set(detail["summary"]["experiments"]) == {"A", "B", "C", "D"}
    assert len(detail["summary"]["experiments"]) == 4
    assert {"B_vs_A", "C_vs_B", "D_vs_C"} <= set(detail["derived"])

    traces_response = client.get(f"/api/runs/{run_id}/traces")
    assert traces_response.status_code == 200
    traces = traces_response.json()["traces"]
    assert len(traces) == 4
    assert {trace["experiment"] for trace in traces} == {"A", "B", "C", "D"}
    assert all(trace["trace_status"] == "ready" for trace in traces)

    d_trace = next(trace for trace in traces if trace["experiment"] == "D")
    assert d_trace["success"] is True
    actions = {
        event["action"]
        for event in d_trace["events"]
        if event["action"] is not None
    }
    assert {"PLAN", "RETRIEVE", "EXECUTE", "SUMMARIZE"} <= actions

    state_refs = [
        ref
        for event in d_trace["events"]
        for ref in event["state_refs"]
    ]
    assert state_refs
    assert any(
        ref["kind"] == "plan_vector"
        and ref["shape"] == [64]
        and ref["nbytes"] == 256
        for ref in state_refs
    )

    for metric_name in (
        "memory_retrieved",
        "memory_used",
        "memory_effective",
        "memory_harmful",
    ):
        assert metric_name in d_trace["metrics"]
        assert d_trace["metrics"][metric_name] >= 0

    dashboard_response = client.get("/dashboard/")
    assert dashboard_response.status_code == 200
    dashboard_html = dashboard_response.text
    for text in (
        "AgentIPC Dashboard",
        "A/B/C/D",
        "Agent Timeline",
        "State",
        "Memory",
    ):
        assert text in dashboard_html

    js_response = client.get("/dashboard/app.js")
    assert js_response.status_code == 200
    assert js_response.text.strip()
    assert "/api/runs" in js_response.text
    assert "javascript" in js_response.headers["content-type"].lower()

    css_response = client.get("/dashboard/styles.css")
    assert css_response.status_code == 200
    assert css_response.text.strip()
    assert "text/css" in css_response.headers["content-type"].lower()
