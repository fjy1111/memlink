"""HumanEval code-generation adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.benchmark.datasets.base import (
    DatasetAdapter,
    as_str_list,
    discover_split_files,
    get_field,
    get_optional,
    has_field,
    split_names,
    to_plain_python,
)
from app.benchmark.datasets.models import (
    BenchmarkCase,
    CodeGenerationEvaluation,
    CodeGenerationInput,
    TaskType,
)


class HumanEvalAdapter(DatasetAdapter):
    """Load HumanEval Parquet/JSON with prompt and tests kept separate."""

    dataset_name = "humaneval"
    task_type = TaskType.CODE_GENERATION
    grouped = False

    def source_files(self, split: str) -> list[Path]:
        directory = self.data_root / "HumanEval" / "openai_humaneval"
        found = discover_split_files(directory, split)
        if found:
            return found
        canonical = split_names(split)[0]
        return [directory / f"{canonical}-00000-of-00001.parquet"]

    def parse_record(self, record: dict[str, Any], split: str) -> BenchmarkCase:
        record = to_plain_python(record)
        if not isinstance(record, dict):
            raise TypeError("HumanEval record must be an object")
        task_id = str(get_optional(record, "task_id", default="") or "")
        prompt = str(get_field(record, "prompt"))
        if not prompt.strip():
            raise ValueError("HumanEval prompt must be non-empty")
        if not task_id:
            task_id = prompt
        reference_code = str(
            get_optional(record, "canonical_solution", "reference_code") or ""
        )
        raw_tests = get_optional(record, "test", "tests")
        tests = as_str_list(raw_tests)
        entry_point = get_optional(record, "entry_point")
        entry_point_text = None if entry_point is None else str(entry_point)
        metadata: dict[str, Any] = {}
        if has_field(record, "task_id"):
            metadata["task_id"] = to_plain_python(get_optional(record, "task_id"))
        return BenchmarkCase(
            case_id=f"humaneval:{split}:{task_id}",
            dataset=self.dataset_name,
            split=split,
            task_type=self.task_type,
            group_id=str(task_id),
            sequence_index=0,
            input=CodeGenerationInput(prompt=prompt),
            evaluation=CodeGenerationEvaluation(
                reference_code=reference_code,
                tests=tests,
                entry_point=entry_point_text,
            ),
            metadata=metadata,
        )