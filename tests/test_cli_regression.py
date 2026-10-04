from pathlib import Path
import socket

import pytest

from agentipc.cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = PROJECT_ROOT / "tests/scenarios"


def test_all_product_cli_smoke_is_offline_and_uses_external_results_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("core CLI acceptance must be fully offline")

    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    monkeypatch.chdir(tmp_path)
    results_root = tmp_path / "cli-results"

    commands = [
        ["version"],
        ["doctor"],
        ["doctor", "--json"],
        ["demo", "--provider", "mock"],
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
        ],
        [
            "run-scenario",
            "knowledge",
            "--provider",
            "mock",
            "--results-root",
            str(results_root),
            "--scenario-root",
            str(SCENARIO_ROOT),
        ],
        [
            "run-scenario",
            "codeact",
            "--provider",
            "mock",
            "--results-root",
            str(results_root),
            "--scenario-root",
            str(SCENARIO_ROOT),
        ],
    ]

    for command in commands:
        assert main(command) == 0

    assert not (tmp_path / ".agentipc").exists()
    assert not (tmp_path / "results").exists()
    assert not list(tmp_path.glob("*.db"))
    assert not list(tmp_path.glob("*.sqlite*"))
    assert not list(tmp_path.glob("*trace*"))
