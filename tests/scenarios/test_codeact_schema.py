import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentipc.scenarios.models import (
    CodeActExpected,
    CodeActTask,
    load_codeact_tasks,
    load_knowledge_tasks,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CODEACT_ROOT = PROJECT_ROOT / "tests/scenarios" / "codeact_chain"
CODEACT_TASKS_PATH = CODEACT_ROOT / "tasks.json"
KNOWLEDGE_TASKS_PATH = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain" / "tasks.json"


def _task_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "group_id": "codeact-schema",
        "round": 2,
        "description": "Compute a deterministic result.",
        "code": 'import json\nprint(json.dumps(1))\n',
        "input_artifacts": ["data/input.txt"],
        "expected": {"result": 1},
        "reuse_hint": {
            "source_rounds": [1],
            "topics": ["codeact"],
            "expected_reuse": True,
        },
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize("value", [None, "ok", True, 7, 1.25])
def test_codeact_expected_accepts_json_scalars(value: object) -> None:
    assert CodeActExpected(result=value).result == value


def test_codeact_expected_accepts_list_result() -> None:
    assert CodeActExpected(result=[1, "two", False, None]).result == [
        1,
        "two",
        False,
        None,
    ]


def test_codeact_expected_accepts_dict_result() -> None:
    assert CodeActExpected(result={"value": 42}).result == {"value": 42}


def test_codeact_expected_accepts_nested_json_result() -> None:
    value = {"items": [1, {"ok": True, "ratio": 0.5}], "missing": None}
    assert CodeActExpected(result=value).result == value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_codeact_expected_rejects_non_finite_float(value: float) -> None:
    with pytest.raises(ValidationError):
        CodeActExpected(result=value)


@pytest.mark.parametrize("value", [(1, 2), {1, 2}, b"bytes", object()])
def test_codeact_expected_rejects_non_json_types(value: object) -> None:
    with pytest.raises(ValidationError):
        CodeActExpected(result=value)


def test_codeact_expected_rejects_non_string_dict_key() -> None:
    with pytest.raises(ValidationError):
        CodeActExpected(result={1: "bad"})


def test_valid_codeact_task() -> None:
    task = CodeActTask.model_validate(_task_data())
    assert task.group_id == "codeact-schema"
    assert task.round == 2
    assert task.input_artifacts == ["data/input.txt"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("group_id", ""),
        ("description", ""),
        ("code", ""),
    ],
)
def test_codeact_task_rejects_empty_required_string(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        CodeActTask.model_validate(_task_data(**{field: value}))


def test_codeact_task_rejects_round_zero() -> None:
    with pytest.raises(ValidationError):
        CodeActTask.model_validate(_task_data(round=0))


def test_codeact_task_rejects_input_artifacts_non_list() -> None:
    with pytest.raises(ValidationError):
        CodeActTask.model_validate(_task_data(input_artifacts="data/input.txt"))


def test_codeact_task_rejects_empty_input_artifact_list() -> None:
    with pytest.raises(ValidationError):
        CodeActTask.model_validate(_task_data(input_artifacts=[]))


def test_codeact_task_rejects_empty_artifact() -> None:
    with pytest.raises(ValidationError):
        CodeActTask.model_validate(_task_data(input_artifacts=[""]))


def test_codeact_task_rejects_duplicate_artifact() -> None:
    with pytest.raises(ValidationError):
        CodeActTask.model_validate(
            _task_data(input_artifacts=["data/input.txt", "data/input.txt"])
        )


@pytest.mark.parametrize(
    "artifact",
    [
        "/tmp/input.txt",
        "../input.txt",
        "data/../input.txt",
        "data\\input.txt",
        "./data/input.txt",
    ],
)
def test_codeact_task_rejects_non_portable_artifact_path(artifact: str) -> None:
    with pytest.raises(ValidationError):
        CodeActTask.model_validate(_task_data(input_artifacts=[artifact]))


def test_codeact_task_rejects_source_round_not_before_current() -> None:
    with pytest.raises(ValidationError):
        CodeActTask.model_validate(
            _task_data(
                reuse_hint={
                    "source_rounds": [2],
                    "topics": ["codeact"],
                    "expected_reuse": True,
                }
            )
        )


def test_load_codeact_tasks_rejects_wrong_path_type() -> None:
    with pytest.raises(TypeError):
        load_codeact_tasks(object())  # type: ignore[arg-type]


def test_load_codeact_tasks_missing_file_propagates(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_codeact_tasks(tmp_path / "missing.json")


@pytest.mark.parametrize("payload", [{}, []])
def test_load_codeact_tasks_requires_non_empty_top_level_list(
    tmp_path: Path,
    payload: object,
) -> None:
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_codeact_tasks(path)


def test_load_codeact_tasks_valid_list_and_preserves_order(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    payload = [
        _task_data(
            round=1,
            reuse_hint={
                "source_rounds": [],
                "topics": [],
                "expected_reuse": False,
            },
        ),
        _task_data(round=2),
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    tasks = load_codeact_tasks(path)

    assert [task.round for task in tasks] == [1, 2]


def test_load_codeact_tasks_rejects_duplicate_group_round(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    payload = [
        _task_data(),
        _task_data(description="Duplicate key."),
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate codeact task"):
        load_codeact_tasks(path)


def test_load_codeact_tasks_malformed_json_propagates(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text("[", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_codeact_tasks(path)


def test_knowledge_tasks_still_load_successfully() -> None:
    tasks = load_knowledge_tasks(KNOWLEDGE_TASKS_PATH)
    assert tasks


def test_real_codeact_chain_contract_and_fixture_paths() -> None:
    tasks = load_codeact_tasks(CODEACT_TASKS_PATH)

    assert len(tasks) == 10
    assert [task.round for task in tasks] == list(range(1, 11))
    assert {task.group_id for task in tasks} == {"local-codeact-analysis-chain"}

    root = CODEACT_ROOT.resolve()
    for task in tasks:
        for artifact in task.input_artifacts:
            path = (CODEACT_ROOT / artifact).resolve()
            assert path.is_file()
            assert path.is_relative_to(root)

    round2 = tasks[1]
    round3 = tasks[2]
    round8 = tasks[7]
    round9 = tasks[8]

    assert round8.code == round2.code
    assert round8.input_artifacts == round2.input_artifacts
    assert round8.expected.result == round2.expected.result

    assert round9.code == round3.code
    assert round9.input_artifacts == round3.input_artifacts
    assert round9.expected.result == round3.expected.result
