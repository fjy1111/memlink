"""QReCC conversational QA adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.benchmark.datasets.base import (
    DatasetAdapter,
    as_history,
    as_int,
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


class QReCCAdapter(DatasetAdapter):
    """Load QReCC JSON conversations into grouped benchmark cases."""

    dataset_name = "qrecc"
    task_type = TaskType.CONVERSATIONAL_QA
    grouped = True

    SPLIT_FILES = {
        "train": Path("QReCC") / "qrecc-training.json",
        "training": Path("QReCC") / "qrecc-training.json",
        "test": Path("QReCC") / "qrecc-test.json",
    }

    def source_files(self, split: str) -> list[Path]:
        relative = self.SPLIT_FILES.get(split.strip().lower())
        if relative is None:
            allowed = ", ".join(sorted(set(map(str, self.SPLIT_FILES))))
            raise ValueError(f"Unsupported QReCC split: {split}. Expected one of {allowed}")
        return [self.data_root / relative]

    def parse_record(self, record: dict[str, Any], split: str) -> BenchmarkCase:
        record = to_plain_python(record)
        if not isinstance(record, dict):
            raise TypeError("QReCC record must be an object")
        group_id = str(get_field(record, "Conversation_no"))
        sequence_index = as_int(get_field(record, "Turn_no"))
        question = str(get_field(record, "Question")).strip()
        history = as_history(get_optional(record, "Context", default=[]))
        answer = str(get_optional(record, "Answer") or "")
        metadata: dict[str, Any] = {}
        for field_name in ("Rewrite", "Answer_URL", "Passages", "Conversation_source"):
            if has_field(record, field_name):
                metadata[field_name] = to_plain_python(get_optional(record, field_name))
        return BenchmarkCase(
            case_id=f"qrecc:{split}:{group_id}:{sequence_index}",
            dataset=self.dataset_name,
            split=split,
            task_type=self.task_type,
            group_id=group_id,
            sequence_index=sequence_index,
            input=ConversationalQAInput(question=question, history=history),
            evaluation=ConversationalQAEvaluation(answer=answer),
            metadata=metadata,
        )