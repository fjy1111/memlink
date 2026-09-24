"""TopiOCQA adapter tests."""

import json
from pathlib import Path

import pytest

from app.benchmark.datasets.base import DATASET_ROOT_ENV, DatasetRootNotSetError
from app.benchmark.datasets.models import TaskType, leaked_runtime_keys
from app.benchmark.datasets.topiocqa import TopiOCQAAdapter


def write_topiocqa(root: Path, split_name: str, records: list[dict]) -> None:
    path = root / "TopiOCQA" / "data" / f"topiocqa_{split_name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def conversation_records() -> list[dict]:
    return [
        {
            "Conversation_no": 7,
            "Turn_no": 3,
            "Question": "Where do they live?",
            "Context": ["What is a lynx?", "A wild cat", "Are they endangered?", "Some populations are"],
            "Answer": "Forests of the northern hemisphere",
            "Additional_answers": ["Boreal forests"],
            "Topic": "Lynx",
            "Topic_section": "Habitat",
            "is_nq": False,
            "Rationale": "gold rationale must not leak",
            "Gold_passage": {"title": "Lynx", "text": "secret gold passage"},
        },
        {
            "Conversation_no": 8,
            "Turn_no": 1,
            "Question": "What is Python?",
            "Context": [],
            "Answer": "A programming language",
            "Additional_answers": [],
            "Topic": "Python",
            "Topic_section": "Overview",
            "is_nq": True,
            "Rationale": "other rationale",
            "Gold_passage": "other gold",
        },
        {
            "Conversation_no": 7,
            "Turn_no": 1,
            "Question": "What is a lynx?",
            "Context": [],
            "Answer": "A wild cat",
            "Additional_answers": ["A feline"],
            "Topic": "Lynx",
            "Topic_section": "Intro",
            "is_nq": False,
            "Rationale": "first rationale",
            "Gold_passage": {"title": "Lynx", "text": "first gold"},
        },
        {
            "Conversation_no": 7,
            "Turn_no": 2,
            "Question": "Are they endangered?",
            "Context": ["What is a lynx?", "A wild cat"],
            "Answer": "Some populations are",
            "Additional_answers": ["Depends on the species"],
            "Topic": "Lynx",
            "Topic_section": "Conservation",
            "is_nq": True,
            "Rationale": "second rationale",
            "Gold_passage": "second gold",
        },
        {
            "Conversation_no": 9,
            "Turn_no": 1,
            "Question": "What is rust?",
            "Context": [],
            "Answer": "A language",
            "Additional_answers": [],
            "Topic": "Rust",
            "Topic_section": "Overview",
            "is_nq": False,
        },
    ]


def test_second_turn_restores_history_group_and_index(tmp_path: Path) -> None:
    write_topiocqa(tmp_path, "train", conversation_records())
    adapter = TopiOCQAAdapter(data_root=tmp_path)
    groups = adapter.load_groups("train")
    lynx = next(group for group in groups if group.group_id == "7")
    assert [case.sequence_index for case in lynx.cases] == [1, 2, 3]
    second = lynx.cases[1]
    assert second.input.question == "Are they endangered?"
    assert second.input.history == ["What is a lynx?", "A wild cat"]
    assert second.group_id == "7"
    assert second.sequence_index == 2
    assert second.task_type is TaskType.CONVERSATIONAL_QA
    assert second.evaluation.answer == "Some populations are"
    assert second.evaluation.alternative_answers == ["Depends on the species"]
    assert second.metadata["Topic"] == "Lynx"
    assert second.metadata["Topic_section"] == "Conservation"
    assert second.metadata["is_nq"] is True


def test_gold_fields_do_not_enter_runtime_input(tmp_path: Path) -> None:
    write_topiocqa(tmp_path, "train", conversation_records())
    adapter = TopiOCQAAdapter(data_root=tmp_path)
    second = next(
        case
        for case in adapter.load_cases("train")
        if case.group_id == "7" and case.sequence_index == 2
    )
    payload = second.to_runtime_input()
    dumped = json.dumps(payload)
    assert leaked_runtime_keys(payload) == set()
    assert "Rationale" not in dumped
    assert "Gold_passage" not in dumped
    assert "gold rationale" not in dumped
    assert "secret gold passage" not in dumped
    assert "Some populations are" not in dumped
    assert payload["input"]["question"] == "Are they endangered?"


def test_conversations_are_grouped_and_sorted(tmp_path: Path) -> None:
    write_topiocqa(tmp_path, "train", conversation_records())
    adapter = TopiOCQAAdapter(data_root=tmp_path)
    groups = adapter.load_groups("train")
    assert [group.group_id for group in groups] == ["7", "8", "9"]
    lynx = groups[0]
    assert [case.case_id for case in lynx.cases] == [
        "topiocqa:train:7:1",
        "topiocqa:train:7:2",
        "topiocqa:train:7:3",
    ]


def test_sample_selects_whole_conversations_with_stable_ids(tmp_path: Path) -> None:
    write_topiocqa(tmp_path, "train", conversation_records())
    adapter = TopiOCQAAdapter(data_root=tmp_path)
    first = adapter.sample("train", n=2, seed=2026, experiment="text")
    second = adapter.sample("train", n=2, seed=2026, experiment="structured")
    third = adapter.sample("train", n=2, seed=2026, experiment="structured_no_memory")
    assert [case.case_id for case in first] == [case.case_id for case in second]
    assert [case.case_id for case in first] == [case.case_id for case in third]
    grouped_ids = {case.group_id for case in first}
    assert len(grouped_ids) == 2
    original_groups = {group.group_id: group for group in adapter.load_groups("train")}
    for group_id in grouped_ids:
        sampled_turns = [
            case.sequence_index for case in first if case.group_id == group_id
        ]
        original_turns = [
            case.sequence_index for case in original_groups[group_id].cases
        ]
        assert sampled_turns == original_turns
        assert sampled_turns == sorted(sampled_turns)

def test_adapter_requires_dataset_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATASET_ROOT_ENV, raising=False)
    with pytest.raises(DatasetRootNotSetError, match=DATASET_ROOT_ENV):
        TopiOCQAAdapter()
