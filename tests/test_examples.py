"""Checked-in consecutive task group tests."""

import json
from pathlib import Path


def test_two_consecutive_task_groups_have_three_related_tasks_each() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "examples"
        / "continuous_tasks.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert set(payload["groups"]) == {"rag", "api"}
    for group in payload["groups"].values():
        tasks = group["tasks"]
        assert len(tasks) == 3
        assert len({task["task_topic"] for task in tasks}) == 1
        assert all(task["title"] and task["prompt"] for task in tasks)
