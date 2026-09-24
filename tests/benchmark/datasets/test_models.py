"""Dataset model, sampling, and runtime-isolation tests."""

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app.benchmark.datasets.base import (
    DATASET_ROOT_ENV,
    DatasetRootNotSetError,
    group_cases,
    resolve_dataset_root,
    sample_cases,
    sample_groups,
)
from app.benchmark.datasets.models import (
    RUNTIME_FORBIDDEN_KEYS,
    BenchmarkCase,
    BenchmarkGroup,
    CodeGenerationEvaluation,
    CodeGenerationInput,
    ConversationalQAEvaluation,
    ConversationalQAInput,
    RetrievalDocument,
    RetrievalQAEvaluation,
    RetrievalQAInput,
    SupportingFact,
    TaskType,
    leaked_runtime_keys,
)


def make_conversational_case(
    *,
    group_id: str,
    sequence_index: int,
    question: str,
    history: list[str],
    answer: str,
) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=f"topiocqa:train:{group_id}:{sequence_index}",
        dataset="topiocqa",
        split="train",
        task_type=TaskType.CONVERSATIONAL_QA,
        group_id=group_id,
        sequence_index=sequence_index,
        input=ConversationalQAInput(question=question, history=history),
        evaluation=ConversationalQAEvaluation(answer=answer),
        metadata={"Topic": "demo"},
    )


def test_task_type_values() -> None:
    assert TaskType.CONVERSATIONAL_QA == "conversational_qa"
    assert TaskType.RETRIEVAL_QA == "retrieval_qa"
    assert TaskType.CODE_GENERATION == "code_generation"


def test_benchmark_case_rejects_mismatched_payloads() -> None:
    with pytest.raises(ValidationError):
        BenchmarkCase(
            case_id="bad",
            dataset="hotpotqa",
            split="train",
            task_type=TaskType.RETRIEVAL_QA,
            group_id="1",
            sequence_index=0,
            input=ConversationalQAInput(question="q", history=[]),
            evaluation=RetrievalQAEvaluation(answer="a"),
        )


def test_supporting_fact_rejects_negative_sentence_id() -> None:
    with pytest.raises(ValidationError):
        SupportingFact(title="Paris", sentence_id=-1)


def test_code_generation_tests_become_builtin_str_list() -> None:
    evaluation = CodeGenerationEvaluation(
        reference_code="def add(a, b):\n    return a + b\n",
        tests=np.array(["assert add(1, 2) == 3", "assert add(0, 0) == 0"]),
        entry_point="add",
    )
    assert type(evaluation.tests) is list
    assert evaluation.tests == ["assert add(1, 2) == 3", "assert add(0, 0) == 0"]
    assert all(type(item) is str for item in evaluation.tests)


def test_code_generation_parses_string_like_tests() -> None:
    evaluation = CodeGenerationEvaluation(
        reference_code="x = 1",
        tests="['assert True', 'assert 1 == 1']",
    )
    assert evaluation.tests == ["assert True", "assert 1 == 1"]


def test_conversational_runtime_input_omits_gold_fields() -> None:
    case = make_conversational_case(
        group_id="9",
        sequence_index=2,
        question="What is the habitat?",
        history=["What is a cat?", "A mammal"],
        answer="Forests and homes",
    )
    payload = case.to_runtime_input()
    assert payload["input"] == {
        "question": "What is the habitat?",
        "history": ["What is a cat?", "A mammal"],
    }
    assert "evaluation" not in payload
    assert "metadata" not in payload
    assert leaked_runtime_keys(payload) == set()
    assert RUNTIME_FORBIDDEN_KEYS.isdisjoint(payload["input"].keys())


def test_retrieval_runtime_input_omits_supporting_facts() -> None:
    case = BenchmarkCase(
        case_id="hotpotqa:train:hp-1",
        dataset="hotpotqa",
        split="train",
        task_type=TaskType.RETRIEVAL_QA,
        group_id="hp-1",
        sequence_index=0,
        input=RetrievalQAInput(
            question="Which city is the capital of France?",
            documents=[
                RetrievalDocument(
                    title="Paris",
                    sentences=["Paris is the capital of France."],
                )
            ],
        ),
        evaluation=RetrievalQAEvaluation(
            answer="Paris",
            supporting_facts=[SupportingFact(title="Paris", sentence_id=0)],
        ),
        metadata={"type": "bridge", "level": "easy"},
    )
    payload = case.to_runtime_input()
    assert payload["input"]["documents"][0]["title"] == "Paris"
    assert leaked_runtime_keys(payload) == set()
    assert "supporting_facts" not in payload["input"]
    assert "answer" not in payload["input"]


def test_code_runtime_input_omits_reference_and_tests() -> None:
    case = BenchmarkCase(
        case_id="mbpp:train:1",
        dataset="mbpp",
        split="train",
        task_type=TaskType.CODE_GENERATION,
        group_id="1",
        sequence_index=0,
        input=CodeGenerationInput(prompt="Write add(a, b)."),
        evaluation=CodeGenerationEvaluation(
            reference_code="def add(a, b):\n    return a + b\n",
            tests=["assert add(1, 2) == 3"],
        ),
    )
    payload = case.to_runtime_input()
    assert payload["input"] == {"prompt": "Write add(a, b)."}
    assert leaked_runtime_keys(payload) == set()


def test_group_sorts_turns_by_sequence_index() -> None:
    later = make_conversational_case(
        group_id="3",
        sequence_index=3,
        question="Q3",
        history=["Q1", "A1", "Q2", "A2"],
        answer="A3",
    )
    first = make_conversational_case(
        group_id="3",
        sequence_index=1,
        question="Q1",
        history=[],
        answer="A1",
    )
    second = make_conversational_case(
        group_id="3",
        sequence_index=2,
        question="Q2",
        history=["Q1", "A1"],
        answer="A2",
    )
    grouped = group_cases([later, first, second])
    assert len(grouped) == 1
    assert [case.sequence_index for case in grouped[0].cases] == [1, 2, 3]


def test_sample_cases_rejects_conversational_turns() -> None:
    cases = [
        make_conversational_case(
            group_id="1",
            sequence_index=1,
            question="Q",
            history=[],
            answer="A",
        )
    ]
    with pytest.raises(ValueError, match="禁止对 TopiOCQA/QReCC"):
        sample_cases(cases, n=1, seed=2026)


def test_sample_groups_is_seed_deterministic() -> None:
    groups = [
        BenchmarkGroup(
            group_id=str(index),
            dataset="topiocqa",
            split="train",
            task_type=TaskType.CONVERSATIONAL_QA,
            cases=[
                make_conversational_case(
                    group_id=str(index),
                    sequence_index=1,
                    question=f"Q{index}",
                    history=[],
                    answer=f"A{index}",
                )
            ],
        )
        for index in range(1, 6)
    ]
    first = [group.group_id for group in sample_groups(groups, n=2, seed=2026)]
    second = [group.group_id for group in sample_groups(groups, n=2, seed=2026)]
    assert first == second
    assert first == [
        group.group_id
        for group in sample_groups(groups, n=2, seed=2026, )
    ]


def test_missing_dataset_root_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATASET_ROOT_ENV, raising=False)
    with pytest.raises(DatasetRootNotSetError, match=DATASET_ROOT_ENV):
        resolve_dataset_root()


def test_explicit_data_root_does_not_require_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(DATASET_ROOT_ENV, raising=False)
    resolved = resolve_dataset_root(tmp_path)
    assert resolved == tmp_path