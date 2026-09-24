"""Dataset path resolution, record normalization, and sampling helpers."""

from __future__ import annotations

import ast
import json
import os
import random
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

from app.benchmark.datasets.models import (
    BenchmarkCase,
    BenchmarkGroup,
    TaskType,
)


DEFAULT_SEED = 2026
DATASET_ROOT_ENV = "MEMLINK_DATASET_ROOT"
T = TypeVar("T")
_MISSING = object()

SPLIT_ALIASES: dict[str, tuple[str, ...]] = {
    "train": ("train", "training"),
    "training": ("train", "training"),
    "validation": ("validation", "valid", "dev", "val"),
    "valid": ("validation", "valid", "dev", "val"),
    "dev": ("validation", "valid", "dev", "val"),
    "val": ("validation", "valid", "dev", "val"),
    "test": ("test",),
    "prompt": ("prompt",),
}


class DatasetRootNotSetError(RuntimeError):
    """Raised when no dataset root was provided and the env var is missing."""


def resolve_dataset_root(explicit: str | Path | None = None) -> Path:
    """Resolve the dataset root from an argument or ``MEMLINK_DATASET_ROOT``.

    A machine-specific absolute path is never used as a silent default.
    """

    if explicit is not None:
        text = str(explicit).strip()
        if not text:
            raise DatasetRootNotSetError(
                "data_root 为空。请传入数据根目录，或设置环境变量 "
                f"{DATASET_ROOT_ENV}。"
            )
        return Path(text).expanduser()

    raw = os.environ.get(DATASET_ROOT_ENV)
    if raw is None or not str(raw).strip():
        raise DatasetRootNotSetError(
            f"未设置环境变量 {DATASET_ROOT_ENV}。请将其指向包含 "
            "TopiOCQA、QReCC、HotpotQA、MBPP 和 HumanEval 的数据根目录。"
            "拒绝使用机器相关的默认绝对路径。"
        )
    return Path(str(raw).strip()).expanduser()


def split_names(split: str) -> tuple[str, ...]:
    """Return filename prefixes accepted for a logical split."""

    normalized = split.strip().lower()
    if not normalized:
        raise ValueError("split must be a non-empty string")
    return SPLIT_ALIASES.get(normalized, (normalized,))


def canonical_split(split: str) -> str:
    """Return the stable split name used in case IDs."""

    return split_names(split)[0]


def to_plain_python(value: Any) -> Any:
    """Convert Arrow / NumPy / nested array values into plain Python."""

    if value is None:
        return None

    module = type(value).__module__ or ""
    if module.startswith("pyarrow"):
        if hasattr(value, "to_pylist") and callable(value.to_pylist):
            return to_plain_python(value.to_pylist())
        if hasattr(value, "as_py") and callable(value.as_py):
            return to_plain_python(value.as_py())
        if hasattr(value, "tolist") and callable(value.tolist):
            return to_plain_python(value.tolist())

    if isinstance(value, np.ndarray):
        return to_plain_python(value.tolist())
    if isinstance(value, np.generic):
        return to_plain_python(value.item())

    if isinstance(value, Mapping):
        return {
            str(to_plain_python(key)): to_plain_python(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [to_plain_python(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [to_plain_python(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8")
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    return value


def as_int(value: Any) -> int:
    """Convert a normalized numeric value to ``int``."""

    value = to_plain_python(value)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Cannot convert {value!r} to int")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(value.strip())
    raise ValueError(f"Cannot convert {value!r} to int")


def as_bool(value: Any) -> bool:
    """Convert common dataset boolean encodings to ``bool``."""

    value = to_plain_python(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ValueError(f"Cannot convert {value!r} to bool")


def as_str_list(value: Any) -> list[str]:
    """Normalize lists, arrays, and string-like lists into ``list[str]``."""

    value = to_plain_python(value)
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = ast.literal_eval(stripped)
            except (SyntaxError, ValueError):
                parsed = None
            if isinstance(parsed, (list, tuple)):
                return [str(item) for item in parsed if str(item).strip()]
        return [value] if value else []
    if isinstance(value, Mapping):
        items: list[str] = []
        for nested in value.values():
            items.extend(as_str_list(nested))
        return items
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items: list[str] = []
        for item in value:
            if isinstance(item, (list, tuple, Mapping)):
                items.extend(as_str_list(item))
            elif item is None:
                continue
            else:
                text = str(item)
                if text:
                    items.append(text)
        return items
    text = str(value)
    return [text] if text else []


def as_history(value: Any) -> list[str]:
    """Normalize conversation context into a list of history strings."""

    value = to_plain_python(value)
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return [str(value)]

    history: list[str] = []
    for item in value:
        item = to_plain_python(item)
        if item is None:
            continue
        if isinstance(item, str):
            history.append(item)
            continue
        if isinstance(item, Mapping):
            question = item.get("Question", item.get("question"))
            answer = item.get("Answer", item.get("answer"))
            if question:
                history.append(str(question))
            if answer is not None and str(answer) != "":
                history.append(str(answer))
            elif question is None:
                history.append(json.dumps(item, ensure_ascii=False))
            continue
        if isinstance(item, Sequence) and not isinstance(item, (bytes, bytearray)):
            history.extend(str(part) for part in item if part is not None and str(part) != "")
            continue
        history.append(str(item))
    return history


def has_field(record: Mapping[str, Any], *names: str) -> bool:
    """Return whether any of ``names`` exists on ``record`` (case-insensitive)."""

    lowered = {str(key).lower() for key in record}
    return any(name.lower() in lowered for name in names)


def get_optional(
    record: Mapping[str, Any],
    *names: str,
    default: Any = None,
) -> Any:
    """Return the first present field, ignoring case."""

    lowered = {str(key).lower(): value for key, value in record.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return default


def get_field(record: Mapping[str, Any], *names: str) -> Any:
    """Return a required field or raise ``KeyError``."""

    value = get_optional(record, *names, default=_MISSING)
    if value is _MISSING:
        joined = ", ".join(names)
        raise KeyError(f"Record is missing required field: {joined}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read one JSON object per non-empty line."""

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path} line {line_no}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL object required at {path} line {line_no}")
            records.append(to_plain_python(payload))
    return records


def read_json(path: Path) -> list[dict[str, Any]]:
    """Read a JSON array or a single object from ``path``."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = to_plain_python(payload)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "rows", "records"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return nested
        return [payload]
    raise ValueError(f"Unsupported JSON payload in {path}")


def read_parquet(path: Path) -> list[dict[str, Any]]:
    """Read a Parquet table into a list of plain Python dictionaries."""

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "读取 Parquet 需要安装 pyarrow。请执行 pip install 'pyarrow>=17,<23'"
        ) from exc
    table = pq.read_table(path)
    return [to_plain_python(row) for row in table.to_pylist()]


def read_tabular(path: Path) -> list[dict[str, Any]]:
    """Read JSON, JSONL, or Parquet records from ``path``."""

    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return read_jsonl(path)
    if suffix == ".json":
        return read_json(path)
    if suffix == ".parquet":
        return read_parquet(path)
    raise ValueError(f"Unsupported dataset file type: {path.suffix}")


def discover_split_files(directory: Path, split: str) -> list[Path]:
    """Find split files, preferring Parquet shards when both formats exist."""

    names = split_names(split)
    suffixes = (".parquet", ".json", ".jsonl")
    found: list[Path] = []
    for suffix in suffixes:
        for name in names:
            exact = directory / f"{name}{suffix}"
            if exact.is_file():
                found.append(exact)
            found.extend(sorted(directory.glob(f"{name}-*{suffix}")))
            subdir = directory / name
            if subdir.is_dir():
                found.extend(sorted(subdir.glob(f"*{suffix}")))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in found:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    parquet_files = [path for path in unique if path.suffix.lower() == ".parquet"]
    return parquet_files or unique


def _natural_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, value)


def sample_items(
    items: Sequence[T],
    n: int,
    seed: int = DEFAULT_SEED,
    *,
    key: Callable[[T], str],
) -> list[T]:
    """Sample ``n`` items with a stable sort and a fixed RNG seed."""

    if n < 1:
        raise ValueError("n must be >= 1")
    if not items:
        raise ValueError("Cannot sample from an empty collection")
    ordered = sorted(items, key=lambda item: _natural_sort_key(str(key(item))))
    if n >= len(ordered):
        return list(ordered)
    rng = random.Random(seed)
    return rng.sample(ordered, k=n)


def group_cases(cases: Sequence[BenchmarkCase]) -> list[BenchmarkGroup]:
    """Group cases by ``group_id`` and sort each group by ``sequence_index``."""

    grouped: dict[str, list[BenchmarkCase]] = {}
    order: list[str] = []
    for case in cases:
        if case.group_id not in grouped:
            grouped[case.group_id] = []
            order.append(case.group_id)
        grouped[case.group_id].append(case)
    groups: list[BenchmarkGroup] = []
    for group_id in order:
        members = grouped[group_id]
        first = members[0]
        groups.append(
            BenchmarkGroup(
                group_id=group_id,
                dataset=first.dataset,
                split=first.split,
                task_type=first.task_type,
                cases=members,
            )
        )
    return groups


def sample_groups(
    groups: Sequence[BenchmarkGroup],
    n: int,
    seed: int = DEFAULT_SEED,
) -> list[BenchmarkGroup]:
    """Sample complete groups; internal case order is preserved."""

    sampled = sample_items(groups, n, seed, key=lambda group: group.group_id)
    return [
        group.model_copy(
            update={
                "cases": sorted(
                    group.cases,
                    key=lambda case: (case.sequence_index, case.case_id),
                )
            }
        )
        for group in sampled
    ]


def sample_cases(
    cases: Sequence[BenchmarkCase],
    n: int,
    seed: int = DEFAULT_SEED,
) -> list[BenchmarkCase]:
    """Sample independent cases. Conversational turns cannot be sampled."""

    if any(
        case.task_type is TaskType.CONVERSATIONAL_QA
        or case.dataset in {"topiocqa", "qrecc"}
        for case in cases
    ):
        raise ValueError(
            "禁止对 TopiOCQA/QReCC 等连续对话任务随机抽取单个 turn；"
            "请使用 sample_groups() 抽取完整 Conversation。"
        )
    return sample_items(cases, n, seed, key=lambda case: case.case_id)


def flatten_groups(groups: Sequence[BenchmarkGroup]) -> list[BenchmarkCase]:
    """Return cases from groups while keeping each group's turn order."""

    return [case for group in groups for case in group.cases]


class DatasetAdapter(ABC):
    """Load, normalize, group, and sample one public benchmark dataset."""

    dataset_name: str
    task_type: TaskType
    grouped: bool = False

    def __init__(self, data_root: str | Path | None = None) -> None:
        self.data_root = resolve_dataset_root(data_root)

    @abstractmethod
    def source_files(self, split: str) -> list[Path]:
        """Return expected source files for ``split``."""

    @abstractmethod
    def parse_record(self, record: dict[str, Any], split: str) -> BenchmarkCase:
        """Convert one raw record into a ``BenchmarkCase``."""

    def parse_records(
        self,
        records: Iterable[dict[str, Any]],
        split: str,
    ) -> list[BenchmarkCase]:
        """Parse an in-memory record sequence, normalizing Arrow/NumPy values."""

        split = canonical_split(split)
        return [
            self.parse_record(to_plain_python(record), split) for record in records
        ]

    def load_records(self, split: str) -> list[dict[str, Any]]:
        """Read raw records from the resolved dataset files."""

        files = self.source_files(split)
        existing = [path for path in files if path.is_file()]
        if not existing:
            expected = ", ".join(str(path) for path in files) or str(
                self.data_root / self.dataset_name
            )
            raise FileNotFoundError(
                "未找到数据集文件。"
                f" dataset={self.dataset_name}, split={split}, expected={expected}"
            )
        records: list[dict[str, Any]] = []
        for path in existing:
            records.extend(read_tabular(path))
        return records

    def load_cases(self, split: str) -> list[BenchmarkCase]:
        """Load and normalize every case in ``split``."""

        return self.parse_records(self.load_records(split), split)

    def load_groups(self, split: str) -> list[BenchmarkGroup]:
        """Load cases grouped by conversation or singleton task id."""

        cases = self.load_cases(split)
        if self.grouped:
            return group_cases(cases)
        return group_cases(cases)

    def sample_groups(
        self,
        split: str,
        n: int,
        seed: int = DEFAULT_SEED,
        experiment: str | None = None,
    ) -> list[BenchmarkGroup]:
        """Sample complete groups. ``experiment`` does not affect case IDs."""

        del experiment
        return sample_groups(self.load_groups(split), n, seed)

    def sample(
        self,
        split: str,
        n: int,
        seed: int = DEFAULT_SEED,
        experiment: str | None = None,
    ) -> list[BenchmarkCase]:
        """Sample cases with a fixed seed.

        Conversational datasets sample whole conversations, then keep the
        original turn order. ``experiment`` is ignored so every mode shares
        the same manifest of case IDs.
        """

        del experiment
        if self.grouped:
            return flatten_groups(self.sample_groups(split, n, seed))
        return sample_cases(self.load_cases(split), n, seed)