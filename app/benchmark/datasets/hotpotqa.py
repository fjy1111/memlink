"""HotpotQA retrieval QA adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.benchmark.datasets.base import (
    DatasetAdapter,
    as_int,
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
    RetrievalDocument,
    RetrievalQAEvaluation,
    RetrievalQAInput,
    SupportingFact,
    TaskType,
)


def parse_documents(context: Any) -> list[RetrievalDocument]:
    """Normalize HotpotQA context into a document list."""

    context = to_plain_python(context)
    if not context:
        return []
    documents: list[RetrievalDocument] = []
    if isinstance(context, dict) and (
        "title" in context or "sentences" in context
    ):
        titles = as_str_list(context.get("title"))
        sentence_groups = to_plain_python(context.get("sentences") or [])
        if not isinstance(sentence_groups, list):
            sentence_groups = []
        for index, title in enumerate(titles):
            sentences = (
                as_str_list(sentence_groups[index])
                if index < len(sentence_groups)
                else []
            )
            documents.append(RetrievalDocument(title=title, sentences=sentences))
        return documents
    if isinstance(context, list):
        for item in context:
            item = to_plain_python(item)
            if isinstance(item, dict):
                documents.append(
                    RetrievalDocument(
                        title=str(item.get("title") or ""),
                        sentences=as_str_list(item.get("sentences")),
                    )
                )
            elif isinstance(item, list) and len(item) >= 2:
                documents.append(
                    RetrievalDocument(
                        title=str(item[0]),
                        sentences=as_str_list(item[1]),
                    )
                )
    return documents


def parse_supporting_facts(value: Any) -> list[SupportingFact]:
    """Normalize HotpotQA supporting facts into evaluation-only objects."""

    value = to_plain_python(value)
    if not value:
        return []
    facts: list[SupportingFact] = []
    if isinstance(value, dict) and (
        "title" in value or "sent_id" in value or "sentence_id" in value
    ):
        titles = as_str_list(value.get("title"))
        sent_ids = to_plain_python(value.get("sent_id", value.get("sentence_id")) or [])
        if not isinstance(sent_ids, list):
            sent_ids = []
        for index, title in enumerate(titles):
            sentence_id = as_int(sent_ids[index]) if index < len(sent_ids) else 0
            facts.append(SupportingFact(title=title, sentence_id=sentence_id))
        return facts
    if isinstance(value, list):
        for item in value:
            item = to_plain_python(item)
            if isinstance(item, dict):
                facts.append(
                    SupportingFact(
                        title=str(item.get("title") or ""),
                        sentence_id=as_int(item.get("sent_id", item.get("sentence_id", 0))),
                    )
                )
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                facts.append(
                    SupportingFact(title=str(item[0]), sentence_id=as_int(item[1]))
                )
    return facts


class HotpotQAAdapter(DatasetAdapter):
    """Load HotpotQA distractor Parquet/JSON into retrieval QA cases."""

    dataset_name = "hotpotqa"
    task_type = TaskType.RETRIEVAL_QA
    grouped = False

    def source_files(self, split: str) -> list[Path]:
        directory = self.data_root / "HotpotQA" / "distractor"
        found = discover_split_files(directory, split)
        if found:
            return found
        canonical = split_names(split)[0]
        return [directory / f"{canonical}-00000-of-00001.parquet"]

    def parse_record(self, record: dict[str, Any], split: str) -> BenchmarkCase:
        record = to_plain_python(record)
        if not isinstance(record, dict):
            raise TypeError("HotpotQA record must be an object")
        record_id = str(get_optional(record, "id", "_id", default="") or "")
        question = str(get_field(record, "question")).strip()
        if not record_id:
            record_id = question
        documents = parse_documents(get_optional(record, "context", default=[]))
        answer = str(get_optional(record, "answer") or "")
        supporting_facts = parse_supporting_facts(
            get_optional(record, "supporting_facts", default=[])
        )
        metadata: dict[str, Any] = {}
        if has_field(record, "type"):
            metadata["type"] = str(get_optional(record, "type"))
        if has_field(record, "level"):
            metadata["level"] = str(get_optional(record, "level"))
        return BenchmarkCase(
            case_id=f"hotpotqa:{split}:{record_id}",
            dataset=self.dataset_name,
            split=split,
            task_type=self.task_type,
            group_id=str(record_id),
            sequence_index=0,
            input=RetrievalQAInput(question=question, documents=documents),
            evaluation=RetrievalQAEvaluation(
                answer=answer,
                supporting_facts=supporting_facts,
            ),
            metadata=metadata,
        )