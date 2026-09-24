"""Unified benchmark case, input, and evaluation models."""

from __future__ import annotations

import ast
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RUNTIME_FORBIDDEN_KEYS = frozenset(
    {
        "evaluation",
        "answer",
        "additional_answers",
        "alternative_answers",
        "reference_code",
        "tests",
        "test",
        "test_list",
        "supporting_facts",
        "gold_passage",
        "rationale",
        "canonical_solution",
        "code",
        "rewrite",
    }
)


class TaskType(StrEnum):
    """Task families supported by the public dataset adapters."""

    CONVERSATIONAL_QA = "conversational_qa"
    RETRIEVAL_QA = "retrieval_qa"
    CODE_GENERATION = "code_generation"


class ConversationalQAInput(BaseModel):
    """Runtime input for a conversational question-answering turn."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    history: list[str] = Field(default_factory=list)


class RetrievalDocument(BaseModel):
    """One retrieved or provided document for retrieval QA."""

    model_config = ConfigDict(extra="forbid")

    title: str
    sentences: list[str] = Field(default_factory=list)


class RetrievalQAInput(BaseModel):
    """Runtime input for retrieval-style QA such as HotpotQA."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    documents: list[RetrievalDocument] = Field(default_factory=list)


class CodeGenerationInput(BaseModel):
    """Runtime input for a code-generation prompt."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)


class ConversationalQAEvaluation(BaseModel):
    """Gold answers for a conversational QA turn."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    alternative_answers: list[str] = Field(default_factory=list)


class SupportingFact(BaseModel):
    """Gold supporting sentence pointer for retrieval QA."""

    model_config = ConfigDict(extra="forbid")

    title: str
    sentence_id: int = Field(ge=0)


class RetrievalQAEvaluation(BaseModel):
    """Gold answer and supporting facts for retrieval QA."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    supporting_facts: list[SupportingFact] = Field(default_factory=list)


def _coerce_str_list(value: Any) -> list[str]:
    """Normalize Arrow / NumPy / string-like values into builtin ``list[str]``."""

    if value is None:
        return []
    if hasattr(value, "to_pylist") and callable(value.to_pylist):
        value = value.to_pylist()
    elif hasattr(value, "tolist") and callable(value.tolist) and not isinstance(
        value, (list, tuple, str, bytes, bytearray)
    ):
        value = value.tolist()
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = ast.literal_eval(stripped)
            except (SyntaxError, ValueError):
                parsed = None
            if isinstance(parsed, (list, tuple)):
                value = list(parsed)
            else:
                value = [value]
        else:
            value = [value]
    elif isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        raise TypeError("tests must be a list of strings")
    tests = [str(item) for item in value if item is not None and str(item).strip()]
    if not tests:
        raise ValueError("tests must contain at least one non-empty string")
    return tests


class CodeGenerationEvaluation(BaseModel):
    """Hidden reference implementation and tests for code generation."""

    model_config = ConfigDict(extra="forbid")

    reference_code: str
    tests: list[str] = Field(min_length=1)
    entry_point: str | None = None

    @field_validator("tests", mode="before")
    @classmethod
    def normalize_tests(cls, value: Any) -> list[str]:
        """Coerce Arrow / NumPy / string-like tests into ``list[str]``."""

        return _coerce_str_list(value)

    @field_validator("tests")
    @classmethod
    def require_builtin_strings(cls, value: list[str]) -> list[str]:
        """Reject NumPy string subclasses after coercion."""

        return [str(item) for item in value]


BenchmarkInput = ConversationalQAInput | RetrievalQAInput | CodeGenerationInput
BenchmarkEvaluation = (
    ConversationalQAEvaluation
    | RetrievalQAEvaluation
    | CodeGenerationEvaluation
)


def collect_mapping_keys(value: Any) -> set[str]:
    """Return lower-cased keys from a nested JSON-like payload."""

    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.add(str(key).lower())
            keys.update(collect_mapping_keys(nested))
    elif isinstance(value, list):
        for item in value:
            keys.update(collect_mapping_keys(item))
    return keys


def leaked_runtime_keys(payload: Any) -> set[str]:
    """Return forbidden gold/evaluation keys present in ``payload``."""

    return collect_mapping_keys(payload) & RUNTIME_FORBIDDEN_KEYS


class BenchmarkCase(BaseModel):
    """One normalized evaluation item with isolated runtime input."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    split: str = Field(min_length=1)
    task_type: TaskType
    group_id: str = Field(min_length=1)
    sequence_index: int = Field(ge=0)
    input: BenchmarkInput
    evaluation: BenchmarkEvaluation
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_task_payload(self) -> "BenchmarkCase":
        expected = {
            TaskType.CONVERSATIONAL_QA: (
                ConversationalQAInput,
                ConversationalQAEvaluation,
            ),
            TaskType.RETRIEVAL_QA: (RetrievalQAInput, RetrievalQAEvaluation),
            TaskType.CODE_GENERATION: (
                CodeGenerationInput,
                CodeGenerationEvaluation,
            ),
        }
        expected_input, expected_eval = expected[self.task_type]
        if not isinstance(self.input, expected_input):
            raise ValueError(
                f"{self.task_type.value} requires {expected_input.__name__}"
            )
        if not isinstance(self.evaluation, expected_eval):
            raise ValueError(
                f"{self.task_type.value} requires {expected_eval.__name__}"
            )
        return self

    def to_runtime_input(self) -> dict[str, Any]:
        """Return the fields an agent runtime may see.

        Evaluation, gold answers, tests, supporting facts, and other
        leakage-prone keys are omitted by construction and re-checked.
        """

        payload = {
            "case_id": self.case_id,
            "dataset": self.dataset,
            "split": self.split,
            "task_type": self.task_type.value,
            "group_id": self.group_id,
            "sequence_index": self.sequence_index,
            "input": self.input.model_dump(mode="json"),
        }
        leaked = leaked_runtime_keys(payload)
        if leaked:
            raise ValueError(
                "Runtime input leaked gold/evaluation fields: "
                + ", ".join(sorted(leaked))
            )
        return payload


class BenchmarkGroup(BaseModel):
    """A conversation or singleton group of benchmark cases."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    split: str = Field(min_length=1)
    task_type: TaskType
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def sort_and_validate_cases(self) -> "BenchmarkGroup":
        for case in self.cases:
            if case.group_id != self.group_id:
                raise ValueError("group_id mismatch between group and case")
            if case.dataset != self.dataset:
                raise ValueError("dataset mismatch between group and case")
            if case.split != self.split:
                raise ValueError("split mismatch between group and case")
            if case.task_type != self.task_type:
                raise ValueError("task_type mismatch between group and case")
        object.__setattr__(
            self,
            "cases",
            sorted(self.cases, key=lambda case: (case.sequence_index, case.case_id)),
        )
        return self