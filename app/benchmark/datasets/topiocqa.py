"""TopiOCQA conversational QA adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.benchmark.datasets.base import (
    DatasetAdapter,
    as_bool,
    as_history,
    as_int,
    as_str_list,
    get_field,
    get_optional,
    has_field,
    to_plain_python,
)
from app.benchmark.datasets.models import (
    BenchmarkCase,
    ConversationalQAEvaluation,
    ConversationalQAInput,
    TaskType,
)


class TopiOCQAAdapter(DatasetAdapter):
    """Load TopiOCQA JSONL conversations into grouped benchmark cases."""

    dataset_name = "topiocqa"
    task_type = TaskType.CONVERSATIONAL_QA
    grouped = True

    SPLIT_FILES = {
        "train": Path("TopiOCQA") / "data" / "topiocqa_train.jsonl",
        "valid": Path("TopiOCQA") / "data" / "topiocqa_valid.jsonl",
        "validation": Path("TopiOCQA") / "data" / "topiocqa_valid.jsonl",
        "dev": Path("TopiOCQA") / "data" / "topiocqa_valid.jsonl",
    }

    def source_files(self, split: str) -> list[Path]:
        relative = self.SPLIT_FILES.get(split.strip().lower())
        if relative is None:
            allowed = ", ".join(sorted(set(self.SPLIT_FILES)))
            raise ValueError(f"Unsupported TopiOCQA split: {split}. Expected one of {allowed}")
        return [self.data_root / relative]

    def parse_record(self, record: dict[str, Any], split: str) -> BenchmarkCase:
        record = to_plain_python(record)
        if not isinstance(record, dict):
            raise TypeError("TopiOCQA record must be an object")
        group_id = str(get_field(record, "Conversation_no"))
        sequence_index = as_int(get_field(record, "Turn_no"))
        question = str(get_field(record, "Question")).strip()
        history = as_history(get_optional(record, "Context", default=[]))
        answer = str(get_optional(record, "Answer") or "")
        alternatives = as_str_list(get_optional(record, "Additional_answers"))
        metadata: dict[str, Any] = {}
        if has_field(record, "Topic"):
            metadata["Topic"] = to_plain_python(get_optional(record, "Topic"))
        if has_field(record, "Topic_section"):
            metadata["Topic_section"] = to_plain_python(get_optional(record, "Topic_section"))
        if has_field(record, "is_nq"):
            metadata["is_nq"] = as_bool(get_optional(record, "is_nq"))
        return BenchmarkCase(
            case_id=f"topiocqa:{split}:{group_id}:{sequence_index}",
            dataset=self.dataset_name,
            split=split,
            task_type=self.task_type,
            group_id=group_id,
            sequence_index=sequence_index,
            input=ConversationalQAInput(question=question, history=history),
            evaluation=ConversationalQAEvaluation(
                answer=answer,
                alternative_answers=alternatives,
            ),
            metadata=metadata,
        )