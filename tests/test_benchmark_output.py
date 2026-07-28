"""Raw output encoding and environment redaction tests."""

import csv
import json
from pathlib import Path

from app.benchmark.environment import collect_environment
from app.benchmark.output import write_csv, write_json


def test_csv_is_excel_compatible_utf8_sig(tmp_path: Path) -> None:
    path = tmp_path / "result.csv"
    write_csv(path, [{"name": "企业故障", "ids": ["a", "b"]}])

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["name"] == "企业故障"
    assert json.loads(row["ids"]) == ["a", "b"]


def test_json_is_utf8_and_environment_contains_no_secret_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEMLINK_DEEPSEEK_API_KEY", "must-not-leak")
    environment = collect_environment()
    path = tmp_path / "environment.json"
    write_json(path, environment)

    payload = path.read_text(encoding="utf-8")
    assert "must-not-leak" not in payload
    assert "python_version" in json.loads(payload)
