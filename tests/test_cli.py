"""CLI smoke tests using the current pytest interpreter and isolated data."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["text", "structured"])
def test_cli_run_demo_offline(mode: str, tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "MEMLINK_LLM_BACKEND": "fake",
            "MEMLINK_EMBEDDING_BACKEND": "fake",
            "MEMLINK_METRICS_DIR": str(tmp_path / mode / "metrics"),
            "MEMLINK_STATE_DIR": str(tmp_path / mode / "states"),
            "MEMLINK_MEMORY_DB_PATH": str(
                tmp_path / mode / "memory" / "shared.db"
            ),
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "run-demo",
            "--mode",
            mode,
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"通信模式：{mode}" in completed.stdout
    assert "任务 ID：" in completed.stdout
    assert "Agent 执行轨迹：" in completed.stdout
    assert "共享记忆命中数：" in completed.stdout


def test_benchmark_cli_is_importable_from_a_fresh_process() -> None:
    """Prevent package import order from hiding circular dependencies."""

    completed = subprocess.run(
        [sys.executable, "-m", "app.benchmark.cli", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "{run,summarize}" in completed.stdout
