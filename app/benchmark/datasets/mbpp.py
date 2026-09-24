"""MBPP code-generation adapter."""

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


class MBPPAdapter(DatasetAdapter):
    """Load MBPP sanitized Parquet into isolated code-generation cases."""

    dataset_name = "mbpp"
    task_type = TaskType.CODE_GENERATION
    grouped = False

    def source_files(self, split: str) -> list[Path]:
        directory = self.data_root / "MBPP" / "sanitized"
        found = discover_split_files(directory, split)
        if found:
            return found
        canonical = split_names(split)[0]
        return [directory / f"{canonical}-00000-of-00001.parquet"]

    def parse_record(self, record: dict[str, Any], split: str) -> BenchmarkCase:
        record = to_plain_python(record)
        if not isinstance(record, dict):
            raise TypeError("MBPP record must be an object")
        task_id = str(get_optional(record, "task_id", default="") or "")
        prompt = str(get_field(record, "prompt", "text")).strip()
        if not task_id:
            task_id = prompt
        reference_code = str(get_optional(record, "code", "reference_code") or "")
        tests = as_str_list(get_optional(record, "test_list", "tests"))
        metadata: dict[str, Any] = {}
        if has_field(record, "source_file"):
            metadata["source_file"] = str(get_optional(record, "source_file") or "")
        if has_field(record, "task_id"):
            metadata["task_id"] = to_plain_python(get_optional(record, "task_id"))
        if has_field(record, "test_imports"):
            metadata["test_imports"] = as_str_list(get_optional(record, "test_imports"))
        return BenchmarkCase(
            case_id=f"mbpp:{split}:{task_id}",
            dataset=self.dataset_name,
            split=split,
            task_type=self.task_type,
            group_id=str(task_id),
            sequence_index=0,
            input=CodeGenerationInput(prompt=prompt),
            evaluation=CodeGenerationEvaluation(
                reference_code=reference_code,
                tests=tests,
            ),
            metadata=metadata,
        )