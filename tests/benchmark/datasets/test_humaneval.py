"""HumanEval adapter tests."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from app.benchmark.datasets.humaneval import HumanEvalAdapter
from app.benchmark.datasets.models import leaked_runtime_keys


PROMPT = '''def has_close_elements(numbers: list[float], threshold: float) -> bool:
    """Check if any two numbers are closer than threshold."""
'''

SOLUTION = '''    for index, first in enumerate(numbers):
        for second in numbers[index + 1:]:
            if abs(first - second) < threshold:
                return True
    return False
'''

TESTS = '''

def check(candidate):
    assert candidate([1.0, 2.0, 3.0], 0.5) is False
    assert candidate([1.0, 2.8, 3.0], 0.3) is True
'''


def write_parquet(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), path)


def parquet_records() -> list[dict]:
    return [
        {
            "task_id": "HumanEval/0",
            "prompt": PROMPT,
            "canonical_solution": SOLUTION,
            "test": TESTS,
            "entry_point": "has_close_elements",
        },
        {
            "task_id": "HumanEval/1",
            "prompt": "def separate_paren_groups(paren_string: str) -> list[str]:\n",
            "canonical_solution": "    return []\n",
            "test": "def check(candidate):\n    assert candidate('') == []\n",
            "entry_point": "separate_paren_groups",
        },
        {
            "task_id": "HumanEval/2",
            "prompt": "def truncate_number(number: float) -> float:\n",
            "canonical_solution": "    return number % 1.0\n",
            "test": "def check(candidate):\n    assert candidate(3.5) == 0.5\n",
            "entry_point": "truncate_number",
        },
    ]


def test_prompt_and_tests_are_strictly_isolated(tmp_path: Path) -> None:
    write_parquet(
        tmp_path / "HumanEval" / "openai_humaneval" / "test-00000-of-00001.parquet",
        parquet_records(),
    )
    adapter = HumanEvalAdapter(data_root=tmp_path)
    case = next(
        item for item in adapter.load_cases("test") if item.metadata["task_id"] == "HumanEval/0"
    )
    assert case.input.prompt == PROMPT
    assert "def check" not in case.input.prompt
    assert case.evaluation.reference_code == SOLUTION
    assert type(case.evaluation.tests) is list
    assert case.evaluation.tests == [TESTS]
    assert case.evaluation.entry_point == "has_close_elements"
    payload = case.to_runtime_input()
    dumped = json.dumps(payload)
    assert leaked_runtime_keys(payload) == set()
    assert payload["input"] == {"prompt": PROMPT}
    assert "canonical_solution" not in dumped
    assert "def check" not in dumped
    assert SOLUTION.strip() not in dumped
    assert "entry_point" not in dumped


def test_humaneval_sample_ids_are_seed_stable(tmp_path: Path) -> None:
    write_parquet(
        tmp_path / "HumanEval" / "openai_humaneval" / "test-00000-of-00001.parquet",
        parquet_records(),
    )
    adapter = HumanEvalAdapter(data_root=tmp_path)
    first = [case.case_id for case in adapter.sample("test", n=2, seed=2026, experiment="text")]
    second = [
        case.case_id
        for case in adapter.sample("test", n=2, seed=2026, experiment="structured")
    ]
    assert first == second
    assert len(first) == 2