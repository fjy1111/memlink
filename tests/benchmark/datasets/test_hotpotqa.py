"""HotpotQA adapter tests."""

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from app.benchmark.datasets.hotpotqa import HotpotQAAdapter
from app.benchmark.datasets.models import leaked_runtime_keys


def write_parquet(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), path)


def parquet_records() -> list[dict]:
    return [
        {
            "id": "hp-1",
            "question": "Which city is the capital of France?",
            "answer": "Paris",
            "type": "bridge",
            "level": "medium",
            "context": {
                "title": ["France", "Paris"],
                "sentences": [
                    ["France is a country in Europe.", "Its official language is French."],
                    ["Paris is a city.", "It is the capital of France."],
                ],
            },
            "supporting_facts": {
                "title": ["Paris"],
                "sent_id": [1],
            },
        },
        {
            "id": "hp-2",
            "question": "Who wrote Hamlet?",
            "answer": "Shakespeare",
            "type": "comparison",
            "level": "easy",
            "context": {
                "title": ["Hamlet", "Shakespeare"],
                "sentences": [
                    ["Hamlet is a play."],
                    ["William Shakespeare wrote Hamlet."],
                ],
            },
            "supporting_facts": {
                "title": ["Shakespeare"],
                "sent_id": [0],
            },
        },
        {
            "id": "hp-3",
            "question": "What is the largest planet?",
            "answer": "Jupiter",
            "type": "bridge",
            "level": "hard",
            "context": {
                "title": ["Solar System"],
                "sentences": [["Jupiter is the largest planet."]],
            },
            "supporting_facts": {
                "title": ["Solar System"],
                "sent_id": [0],
            },
        },
    ]


def test_parquet_context_becomes_document_list(tmp_path: Path) -> None:
    write_parquet(
        tmp_path / "HotpotQA" / "distractor" / "train-00000-of-00001.parquet",
        parquet_records(),
    )
    adapter = HotpotQAAdapter(data_root=tmp_path)
    case = next(item for item in adapter.load_cases("train") if item.group_id == "hp-1")
    assert [document.title for document in case.input.documents] == ["France", "Paris"]
    assert case.input.documents[1].sentences == [
        "Paris is a city.",
        "It is the capital of France.",
    ]
    assert all(isinstance(document.sentences, list) for document in case.input.documents)
    assert all(
        type(sentence) is str
        for document in case.input.documents
        for sentence in document.sentences
    )
    assert case.evaluation.answer == "Paris"
    assert case.evaluation.supporting_facts[0].title == "Paris"
    assert case.evaluation.supporting_facts[0].sentence_id == 1
    assert case.metadata == {"type": "bridge", "level": "medium"}
    payload = case.to_runtime_input()
    dumped = json.dumps(payload)
    assert leaked_runtime_keys(payload) == set()
    assert "supporting_facts" not in dumped
    assert payload["input"]["question"] == "Which city is the capital of France?"
    assert "evaluation" not in payload
    assert "answer" not in payload["input"]


def test_numpy_and_original_list_context_are_normalized(tmp_path: Path) -> None:
    adapter = HotpotQAAdapter(data_root=tmp_path)
    numpy_record = {
        "id": "hp-np",
        "question": "Normalize me",
        "answer": "yes",
        "type": np.str_("bridge"),
        "level": np.str_("easy"),
        "context": {
            "title": np.array(["DocA", "DocB"]),
            "sentences": np.array(
                [np.array(["a0", "a1"], dtype=object), np.array(["b0"], dtype=object)],
                dtype=object,
            ),
        },
        "supporting_facts": {
            "title": np.array(["DocA"]),
            "sent_id": np.array([1], dtype=np.int32),
        },
    }
    list_record = {
        "_id": "hp-json",
        "question": "Original JSON format",
        "answer": "gold",
        "type": "bridge",
        "level": "medium",
        "context": [
            ["Alpha", ["first sentence", "second sentence"]],
            ["Beta", ["only sentence"]],
        ],
        "supporting_facts": [["Alpha", 0], ["Beta", 0]],
    }
    numpy_case, json_case = adapter.parse_records(
        [numpy_record, list_record],
        "validation",
    )
    assert [document.title for document in numpy_case.input.documents] == ["DocA", "DocB"]
    assert numpy_case.input.documents[0].sentences == ["a0", "a1"]
    assert numpy_case.evaluation.supporting_facts[0].sentence_id == 1
    assert json_case.input.documents[0].title == "Alpha"
    assert json_case.input.documents[1].sentences == ["only sentence"]
    assert [
        (fact.title, fact.sentence_id) for fact in json_case.evaluation.supporting_facts
    ] == [("Alpha", 0), ("Beta", 0)]
    assert leaked_runtime_keys(numpy_case.to_runtime_input()) == set()
    assert "supporting_facts" not in json_case.to_runtime_input()["input"]


def test_hotpotqa_sample_ids_are_seed_stable(tmp_path: Path) -> None:
    write_parquet(
        tmp_path / "HotpotQA" / "distractor" / "train-00000-of-00001.parquet",
        parquet_records(),
    )
    adapter = HotpotQAAdapter(data_root=tmp_path)
    first = [case.case_id for case in adapter.sample("train", n=2, seed=2026, experiment="text")]
    second = [
        case.case_id
        for case in adapter.sample("train", n=2, seed=2026, experiment="structured")
    ]
    assert first == second
    assert len(first) == 2