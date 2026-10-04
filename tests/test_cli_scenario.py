import json
from pathlib import Path
import socket

import pytest

from agentipc.cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = PROJECT_ROOT / "tests/scenarios"


def _fail_connect(*args: object, **kwargs: object) -> None:
    raise AssertionError("mock scenario must not access the network")


def _only_result_dir(root: Path) -> Path:
    children = list(root.iterdir())
    assert len(children) == 1
    assert children[0].is_dir()
    return children[0]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_run_scenario_knowledge_uses_real_10_round_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket.socket, "connect", _fail_connect)
    results_root = tmp_path / "knowledge-results"

    exit_code = main(
        [
            "run-scenario",
            "knowledge",
            "--provider",
            "mock",
            "--seed",
            "42",
            "--results-root",
            str(results_root),
            "--scenario-root",
            str(SCENARIO_ROOT),
        ]
    )

    assert exit_code == 0
    result_dir = _only_result_dir(results_root)
    assert {"raw.jsonl", "scenario.json", "environment.json", "work"}.issubset(
        {path.name for path in result_dir.iterdir()}
    )
    assert not (result_dir / "summary.json").exists()
    assert not (result_dir / "report.md").exists()

    raw = _read_jsonl(result_dir / "raw.jsonl")
    assert len(raw) == 10
    assert {record["experiment"]["name"] for record in raw} == {"D"}
    assert all(record["run_result"]["success"] is True for record in raw)
    assert raw[7]["run_result"]["metrics"]["memory_used"] == 1
    assert raw[7]["run_result"]["metrics"]["memory_effective"] == 1
    assert raw[8]["run_result"]["metrics"]["memory_used"] == 1
    assert raw[8]["run_result"]["metrics"]["memory_effective"] == 1

    scenario = json.loads((result_dir / "scenario.json").read_text(encoding="utf-8"))
    assert scenario["kind"] == "scenario"
    assert scenario["scenario"] == "knowledge"
    assert scenario["experiment"] == "D"
    assert scenario["round_count"] == 10
    assert scenario["runtime_success_count"] == 10
    assert scenario["evaluation_success_count"] == 10
    assert len(scenario["rounds"]) == 10


def test_run_scenario_codeact_preserves_real_memory_fast_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket.socket, "connect", _fail_connect)
    results_root = tmp_path / "codeact-results"

    exit_code = main(
        [
            "run-scenario",
            "codeact",
            "--provider",
            "mock",
            "--seed",
            "42",
            "--results-root",
            str(results_root),
            "--scenario-root",
            str(SCENARIO_ROOT),
        ]
    )

    assert exit_code == 0
    result_dir = _only_result_dir(results_root)
    raw = _read_jsonl(result_dir / "raw.jsonl")
    assert len(raw) == 10
    assert {record["experiment"]["name"] for record in raw} == {"D"}

    scenario = json.loads((result_dir / "scenario.json").read_text(encoding="utf-8"))
    assert scenario["round_count"] == 10
    assert scenario["runtime_success_count"] == 10
    assert scenario["evaluation_success_count"] == 10
    assert scenario["metrics_totals"]["tool_call_count"] == 8
    assert scenario["metrics_totals"]["memory_used"] == 2
    assert scenario["metrics_totals"]["memory_effective"] == 2
    assert scenario["metrics_totals"]["memory_harmful"] == 0
    assert scenario["rounds"][7]["execution_operation"] == "identity"
    assert scenario["rounds"][8]["execution_operation"] == "identity"


def test_run_scenario_missing_root_fails_without_downloading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(socket.socket, "connect", _fail_connect)
    missing = tmp_path / "missing-scenarios"

    exit_code = main(
        [
            "run-scenario",
            "knowledge",
            "--scenario-root",
            str(missing),
            "--results-root",
            str(tmp_path / "results"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "scenario root" in captured.err
    assert not missing.exists()
