"""QReCC adapter tests."""

import json
from pathlib import Path

from app.benchmark.datasets.models import leaked_runtime_keys
from app.benchmark.datasets.qrecc import QReCCAdapter


def write_qrecc(root: Path, filename: str, records: list[dict]) -> None:
    path = root / "QReCC" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def conversation_records() -> list[dict]:
    return [
        {
            "Conversation_no": 4,
            "Turn_no": 2,
            "Question": "Who directed it?",
            "Rewrite": "Who directed Inception?",
            "Context": ["What is Inception?", "A science fiction film"],
            "Answer": "Christopher Nolan",
            "Answer_URL": "https://example.invalid/inception",
            "Passages": ["Nolan directed Inception in 2010."],
            "Conversation_source": "trec",
        },
        {
            "Conversation_no": 4,
            "Turn_no": 1,
            "Question": "What is Inception?",
            "Rewrite": "What is Inception?",
            "Context": [],
            "Answer": "A science fiction film",
            "Answer_URL": "https://example.invalid/inception",
            "Passages": ["Inception is a 2010 film."],
            "Conversation_source": "trec",
        },
        {
            "Conversation_no": 5,
            "Turn_no": 1,
            "Question": "What is Dune?",
            "Rewrite": "What is the novel Dune?",
            "Context": [],
            "Answer": "A novel",
            "Answer_URL": "https://example.invalid/dune",
            "Passages": ["Dune is a novel by Frank Herbert."],
            "Conversation_source": "quac",
        },
        {
            "Conversation_no": 6,
            "Turn_no": 1,
            "Question": "What is Unix?",
            "Rewrite": "What is the Unix operating system?",
            "Context": [],
            "Answer": "An operating system",
            "Conversation_source": "trec",
        },
    ]


def test_second_turn_keeps_question_and_puts_rewrite_in_metadata(
    tmp_path: Path,
) -> None:
    write_qrecc(tmp_path, "qrecc-training.json", conversation_records())
    adapter = QReCCAdapter(data_root=tmp_path)
    groups = adapter.load_groups("train")
    inception = next(group for group in groups if group.group_id == "4")
    assert [case.sequence_index for case in inception.cases] == [1, 2]
    second = inception.cases[1]
    assert second.input.question == "Who directed it?"
    assert second.input.history == ["What is Inception?", "A science fiction film"]
    assert second.metadata["Rewrite"] == "Who directed Inception?"
    assert second.metadata["Answer_URL"] == "https://example.invalid/inception"
    assert second.metadata["Passages"] == ["Nolan directed Inception in 2010."]
    assert second.metadata["Conversation_source"] == "trec"
    payload = second.to_runtime_input()
    dumped = json.dumps(payload)
    assert leaked_runtime_keys(payload) == set()
    assert "Rewrite" not in dumped
    assert "Who directed Inception?" not in dumped
    assert "Christopher Nolan" not in dumped
    assert payload["input"]["question"] == "Who directed it?"


def test_sample_uses_complete_conversations_and_stable_ids(tmp_path: Path) -> None:
    write_qrecc(tmp_path, "qrecc-training.json", conversation_records())
    adapter = QReCCAdapter(data_root=tmp_path)
    first = adapter.sample("training", n=2, seed=2026, experiment="text")
    second = adapter.sample("train", n=2, seed=2026, experiment="structured")
    assert [case.case_id for case in first] == [case.case_id for case in second]
    assert len({case.group_id for case in first}) == 2
    for group_id in {case.group_id for case in first}:
        turns = [case.sequence_index for case in first if case.group_id == group_id]
        assert turns == sorted(turns)