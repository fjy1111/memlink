"""MBPP adapter tests."""

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from app.benchmark.datasets.mbpp import MBPPAdapter
from app.benchmark.datasets.models import leaked_runtime_keys


def write_parquet(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), path)


def parquet_records() -> list[dict]:
    return [
        {
            "task_id": 1,
            "prompt": "Write a function to add two numbers.",
            "code": "def add(a, b):\n    return a + b\n",
            "test_list": ["assert add(1, 2) == 3", "assert add(0, 0) == 0"],
            "source_file": "benchmarks/add.py",
        },
        {
            "task_id": 2,
            "prompt": "Write a function to multiply two numbers.",
            "code": "def mul(a, b):\n    return a * b\n",
            "test_list": ["assert mul(2, 3) == 6"],
            "source_file": "benchmarks/mul.py",
        },
        {
            "task_id": 3,
            "prompt": "Write a function to subtract two numbers.",
            "code": "def sub(a, b):\n    return a - b\n",
            "test_list": ["assert sub(5, 2) == 3"],
            "source_file": "benchmarks/sub.py",
        },
    ]


def test_parquet_test_list_is_builtin_str_list(tmp_path: Path) -> None:
    write_parquet(
        tmp_path / "MBPP" / "sanitized" / "train-00000-of-00001.parquet",
        parquet_records(),
    )
    adapter = MBPPAdapter(data_root=tmp_path)
    case = next(item for item in adapter.load_cases("train") if item.metadata["task_id"] == 1)
    assert type(case.evaluation.tests) is list
    assert case.evaluation.tests == ["assert add(1, 2) == 3", "assert add(0, 0) == 0"]
    assert all(type(item) is str for item in case.evaluation.tests)
    assert case.input.prompt == "Write a function to add two numbers."
    assert case.evaluation.reference_code.startswith("def add")
    assert case.metadata["source_file"] == "benchmarks/add.py"
    payload = case.to_runtime_input()
    dumped = json.dumps(payload)
    assert leaked_runtime_keys(payload) == set()
    assert payload["input"] == {"prompt": "Write a function to add two numbers."}
    assert "def add" not in dumped
    assert "assert add" not in dumped
    assert "test_list" not in dumped
    assert "code" not in payload["input"]
    assert "code" not in payload


def test_numpy_and_string_like_tests_are_normalized(tmp_path: Path) -> None:
    adapter = MBPPAdapter(data_root=tmp_path)
    numpy_case, string_case = adapter.parse_records(
        [
            {
                "task_id": np.int32(11),
                "prompt": "Normalize numpy tests",
                "code": "def ident(x):\n    return x\n",
                "test_list": np.array(["assert ident(1) == 1", "assert ident('a') == 'a'"]),
                "source_file": np.str_("ident.py"),
            },
            {
                "task_id": 12,
                "prompt": "Normalize string-like tests",
                "code": "def ping():\n    return 'pong'\n",
                "test_list": "['assert ping() == \"pong\"', 'assert ping() != \"ping\"']",
                "source_file": "ping.py",
            },
        ],
        "train",
    )
    assert type(numpy_case.evaluation.tests) is list
    assert all(type(item) is str for item in numpy_case.evaluation.tests)
    assert numpy_case.evaluation.tests == [
        "assert ident(1) == 1",
        "assert ident('a') == 'a'",
    ]
    assert type(string_case.evaluation.tests) is list
    assert string_case.evaluation.tests == [
        'assert ping() == "pong"',
        'assert ping() != "ping"',
    ]
    assert leaked_runtime_keys(numpy_case.to_runtime_input()) == set()


def test_mbpp_sample_ids_are_seed_stable(tmp_path: Path) -> None:
    write_parquet(
        tmp_path / "MBPP" / "sanitized" / "train-00000-of-00001.parquet",
        parquet_records(),
    )
    adapter = MBPPAdapter(data_root=tmp_path)
    first = [case.case_id for case in adapter.sample("train", n=2, seed=2026, experiment="text")]
    second = [
        case.case_id
        for case in adapter.sample("train", n=2, seed=2026, experiment="structured")
    ]
    assert first == second