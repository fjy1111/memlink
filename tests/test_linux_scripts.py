"""Static portability checks for openEuler deployment artifacts."""

from pathlib import Path

LINUX_SCRIPTS = (
    "setup.sh",
    "test.sh",
    "start.sh",
    "start_ui.sh",
    "run_demo.sh",
    "run_benchmark.sh",
    "collect_environment.sh",
)


def test_linux_scripts_exist_use_lf_and_strict_bash() -> None:
    root = Path(__file__).resolve().parents[1]
    scripts_dir = root / "scripts" / "linux"

    for name in LINUX_SCRIPTS:
        path = scripts_dir / name
        payload = path.read_bytes()
        text = payload.decode("utf-8")
        assert payload.startswith(b"#!/usr/bin/env bash\n")
        assert b"\r\n" not in payload
        assert "set -euo pipefail" in text
        assert "BASH_SOURCE[0]" in text
        assert "/home/" not in text
        assert "E:\\" not in text
        assert "D:\\" not in text


def test_linux_scripts_cover_required_validation_commands() -> None:
    root = Path(__file__).resolve().parents[1]
    scripts_dir = root / "scripts" / "linux"
    combined = "\n".join(
        (scripts_dir / name).read_text(encoding="utf-8")
        for name in LINUX_SCRIPTS
    )

    assert "python3 -m venv .venv" in combined
    assert "-m pip check" in combined
    assert "-m pytest -q" in combined
    assert "run-demo --mode text" in combined
    assert "run-demo --mode structured" in combined
    assert "-m app.benchmark.cli run" in combined
    assert "--rounds" in combined


def test_open_euler_document_has_exact_entry_commands() -> None:
    root = Path(__file__).resolve().parents[1]
    document = (root / "docs" / "openEuler_deployment.md").read_text(
        encoding="utf-8"
    )

    for name in LINUX_SCRIPTS:
        assert f"scripts/linux/{name}" in document
    assert "24.03-LTS-SP3" in document
    assert "不能替代实机验证" in document
