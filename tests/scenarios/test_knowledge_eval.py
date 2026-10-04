from pathlib import Path

import pytest

from agentipc.scenarios.knowledge_eval import (
    KnowledgeEvaluation,
    evaluate_knowledge_answer,
)
from agentipc.scenarios.models import KnowledgeTask, load_knowledge_tasks


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_TASKS_PATH = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain" / "tasks.json"


def _task(answer_contains: list[str]) -> KnowledgeTask:
    return KnowledgeTask.model_validate(
        {
            "group_id": "eval-group",
            "round": 1,
            "query": "query",
            "expected": {
                "answer_contains": answer_contains,
                "evidence_ids": ["doc"],
            },
            "reuse_hint": {
                "source_rounds": [],
                "topics": [],
                "expected_reuse": False,
            },
        }
    )


def test_single_expected_fragment_success() -> None:
    evaluation = evaluate_knowledge_answer(
        _task(["nmcli device status"]),
        "nmcli device status",
    )

    assert evaluation.success is True
    assert evaluation.matched_answer_contains == ["nmcli device status"]
    assert evaluation.missing_answer_contains == []


def test_multiple_expected_fragments_success_and_extra_text_allowed() -> None:
    task = _task(["systemctl status", "journalctl -u", "ss -lntp"])

    evaluation = evaluate_knowledge_answer(
        task,
        "先执行 systemctl status，再用 journalctl -u 看日志，最后运行 ss -lntp。",
    )

    assert evaluation.success is True
    assert evaluation.matched_answer_contains == task.expected.answer_contains
    assert evaluation.missing_answer_contains == []


def test_one_missing_fragment_fails_and_preserves_order() -> None:
    task = _task(["first", "second", "third"])

    evaluation = evaluate_knowledge_answer(task, "third then first")

    assert evaluation.success is False
    assert evaluation.matched_answer_contains == ["first", "third"]
    assert evaluation.missing_answer_contains == ["second"]


def test_all_fragments_missing_fails_and_preserves_missing_order() -> None:
    task = _task(["alpha", "beta", "gamma"])

    evaluation = evaluate_knowledge_answer(task, "unrelated answer")

    assert evaluation.success is False
    assert evaluation.matched_answer_contains == []
    assert evaluation.missing_answer_contains == ["alpha", "beta", "gamma"]


def test_chinese_answer_with_shell_commands() -> None:
    task = _task(["getent hosts", "nmcli device show"])

    evaluation = evaluate_knowledge_answer(
        task,
        "先运行 getent hosts example.com，再用 nmcli device show 查看 DNS。",
    )

    assert evaluation.success is True


def test_empty_answer_is_failure() -> None:
    evaluation = evaluate_knowledge_answer(_task(["required"]), "")

    assert evaluation.success is False
    assert evaluation.matched_answer_contains == []
    assert evaluation.missing_answer_contains == ["required"]


def test_wrong_task_type_raises_type_error() -> None:
    with pytest.raises(TypeError, match="KnowledgeTask"):
        evaluate_knowledge_answer(object(), "answer")  # type: ignore[arg-type]


@pytest.mark.parametrize("answer", [None, b"answer", True, 1])
def test_wrong_answer_type_raises_type_error(answer: object) -> None:
    with pytest.raises(TypeError, match="answer must be a str"):
        evaluate_knowledge_answer(_task(["required"]), answer)  # type: ignore[arg-type]


def test_evaluation_model_json_round_trip() -> None:
    original = KnowledgeEvaluation(
        success=False,
        matched_answer_contains=["one"],
        missing_answer_contains=["two"],
    )

    restored = KnowledgeEvaluation.model_validate_json(original.model_dump_json())

    assert restored == original


def test_real_round_5_requires_all_three_commands() -> None:
    round5 = load_knowledge_tasks(REAL_TASKS_PATH)[4]

    success = evaluate_knowledge_answer(
        round5,
        "systemctl status demo; journalctl -u demo; ss -lntp",
    )
    failure = evaluate_knowledge_answer(
        round5,
        "systemctl status demo; journalctl -u demo",
    )

    assert success.success is True
    assert failure.success is False
    assert failure.missing_answer_contains == ["ss -lntp"]
