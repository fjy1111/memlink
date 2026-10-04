import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentipc.scenarios.knowledge_loader import load_knowledge_documents
from agentipc.scenarios.models import KnowledgeExpected, KnowledgeTask, ReuseHint, load_knowledge_tasks


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_TASKS_PATH = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain" / "tasks.json"
REAL_KNOWLEDGE_ROOT = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain" / "knowledge"


def _valid_task_payload(*, round_number: int = 2) -> dict[str, object]:
    return {
        "group_id": "group",
        "round": round_number,
        "query": "query",
        "expected": {
            "answer_contains": ["answer"],
            "evidence_ids": ["doc"],
        },
        "reuse_hint": {
            "source_rounds": [1] if round_number > 1 else [],
            "topics": ["network"],
            "expected_reuse": round_number > 1,
        },
    }


def test_knowledge_expected_valid() -> None:
    expected = KnowledgeExpected(answer_contains=["nmcli"], evidence_ids=["nm-basics"])
    assert expected.answer_contains == ["nmcli"]
    assert expected.evidence_ids == ["nm-basics"]


def test_reuse_hint_valid() -> None:
    hint = ReuseHint(source_rounds=[1, 2], topics=["network", "dns"], expected_reuse=True)
    assert hint.source_rounds == [1, 2]


def test_knowledge_task_valid_and_json_round_trip() -> None:
    task = KnowledgeTask.model_validate(_valid_task_payload())
    restored = KnowledgeTask.model_validate_json(task.model_dump_json())
    assert restored == task


def test_extra_field_is_rejected() -> None:
    payload = _valid_task_payload()
    payload["extra"] = "nope"

    with pytest.raises(ValidationError):
        KnowledgeTask.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("group_id", "   "),
        ("round", 0),
        ("query", "   "),
    ],
)
def test_invalid_top_level_fields_are_rejected(field: str, value: object) -> None:
    payload = _valid_task_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        KnowledgeTask.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("answer_contains", []),
        ("evidence_ids", []),
        ("answer_contains", ["same", "same"]),
        ("evidence_ids", ["same", "same"]),
    ],
)
def test_invalid_expected_lists_are_rejected(field: str, value: object) -> None:
    payload = _valid_task_payload()
    expected = payload["expected"]
    assert isinstance(expected, dict)
    expected[field] = value

    with pytest.raises(ValidationError):
        KnowledgeTask.model_validate(payload)


def test_duplicate_source_rounds_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ReuseHint(source_rounds=[1, 1], topics=[], expected_reuse=True)


def test_duplicate_topics_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ReuseHint(source_rounds=[], topics=["dns", "dns"], expected_reuse=False)


def test_expected_reuse_requires_source_round() -> None:
    with pytest.raises(ValidationError):
        ReuseHint(source_rounds=[], topics=["network"], expected_reuse=True)


@pytest.mark.parametrize("source_round", [2, 3])
def test_source_round_must_be_before_current_round(source_round: int) -> None:
    payload = _valid_task_payload(round_number=2)
    reuse_hint = payload["reuse_hint"]
    assert isinstance(reuse_hint, dict)
    reuse_hint["source_rounds"] = [source_round]
    reuse_hint["expected_reuse"] = True

    with pytest.raises(ValidationError):
        KnowledgeTask.model_validate(payload)


def test_loader_accepts_valid_list_and_preserves_order(tmp_path: Path) -> None:
    first = _valid_task_payload(round_number=1)
    second = _valid_task_payload(round_number=2)
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps([first, second], ensure_ascii=False), encoding="utf-8")

    tasks = load_knowledge_tasks(path)

    assert [task.round for task in tasks] == [1, 2]


def test_loader_wrong_path_type_is_rejected() -> None:
    with pytest.raises(TypeError):
        load_knowledge_tasks(123)  # type: ignore[arg-type]


def test_loader_missing_path_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_knowledge_tasks(tmp_path / "missing.json")


def test_loader_malformed_json_propagates_decode_error(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("[", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_knowledge_tasks(path)


def test_loader_rejects_top_level_dict(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="top level"):
        load_knowledge_tasks(path)


def test_loader_rejects_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="must not be empty"):
        load_knowledge_tasks(path)


def test_loader_rejects_duplicate_group_and_round(tmp_path: Path) -> None:
    payload = _valid_task_payload(round_number=1)
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps([payload, payload]), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate knowledge task"):
        load_knowledge_tasks(path)


def test_real_knowledge_chain_fixture() -> None:
    tasks = load_knowledge_tasks(REAL_TASKS_PATH)

    assert len(tasks) == 10
    assert [task.round for task in tasks] == list(range(1, 11))
    assert {task.group_id for task in tasks} == {"openeuler-network-service-chain"}

    by_round = {task.round: task for task in tasks}
    assert by_round[8].query == by_round[2].query
    assert by_round[9].query == by_round[3].query
    assert by_round[8].reuse_hint.source_rounds == [2]
    assert by_round[9].reuse_hint.source_rounds == [3]

    query_counts: dict[str, int] = {}
    for task in tasks:
        query_counts[task.query] = query_counts.get(task.query, 0) + 1
    assert sum(count - 1 for count in query_counts.values() if count > 1) >= 2

    document_ids = {doc.document_id for doc in load_knowledge_documents(REAL_KNOWLEDGE_ROOT)}
    for task in tasks:
        assert set(task.expected.evidence_ids) <= document_ids
