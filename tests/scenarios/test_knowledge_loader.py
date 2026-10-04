from pathlib import Path

import pytest
from pydantic import ValidationError

from agentipc.scenarios.knowledge_loader import KnowledgeDocument, load_knowledge_documents


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_KNOWLEDGE_ROOT = PROJECT_ROOT / "tests/scenarios" / "knowledge_chain" / "knowledge"


def _write_markdown(
    path: Path,
    *,
    document_id: str = "doc-1",
    title: str = "示例标题",
    tags: list[str] | None = None,
    body: str = "中文正文",
) -> None:
    tags = tags or ["network"]
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)
    path.write_text(
        "\n".join(
            [
                "---",
                f"document_id: {document_id}",
                f"title: {title}",
                "tags:",
                tags_yaml,
                "---",
                body,
            ]
        ),
        encoding="utf-8",
    )


def test_parse_valid_markdown_and_unicode_body(tmp_path: Path) -> None:
    _write_markdown(
        tmp_path / "01.md",
        document_id="dns-doc",
        title="DNS 检查",
        tags=["dns", "resolver"],
        body="这是包含中文的正文。\n第二行仍然保留。",
    )

    documents = load_knowledge_documents(tmp_path)

    assert documents == [
        KnowledgeDocument(
            document_id="dns-doc",
            title="DNS 检查",
            body="这是包含中文的正文。\n第二行仍然保留。",
            tags=["dns", "resolver"],
        )
    ]


def test_files_are_sorted_by_filename(tmp_path: Path) -> None:
    _write_markdown(tmp_path / "20-second.md", document_id="second")
    _write_markdown(tmp_path / "10-first.md", document_id="first")

    assert [doc.document_id for doc in load_knowledge_documents(tmp_path)] == ["first", "second"]


def test_duplicate_document_id_is_rejected(tmp_path: Path) -> None:
    _write_markdown(tmp_path / "01.md", document_id="same")
    _write_markdown(tmp_path / "02.md", document_id="same")

    with pytest.raises(ValueError, match="duplicate document_id"):
        load_knowledge_documents(tmp_path)


def test_missing_front_matter_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "01.md").write_text("plain body", encoding="utf-8")

    with pytest.raises(ValueError, match="first line"):
        load_knowledge_documents(tmp_path)


def test_unclosed_front_matter_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "01.md").write_text(
        "---\ndocument_id: doc\ntitle: title\ntags:\n  - tag\nbody",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not closed"):
        load_knowledge_documents(tmp_path)


def test_front_matter_must_be_mapping(tmp_path: Path) -> None:
    (tmp_path / "01.md").write_text("---\n- one\n- two\n---\nbody", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a mapping"):
        load_knowledge_documents(tmp_path)


def test_unknown_metadata_field_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "01.md").write_text(
        "---\ndocument_id: doc\ntitle: title\ntags:\n  - tag\nunknown: value\n---\nbody",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_knowledge_documents(tmp_path)


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("   ", "body"),
        ("title", "   \n\t"),
    ],
)
def test_empty_title_or_body_is_rejected(tmp_path: Path, title: str, body: str) -> None:
    _write_markdown(tmp_path / "01.md", title=title, body=body)

    with pytest.raises(ValidationError):
        load_knowledge_documents(tmp_path)


def test_tags_must_be_list(tmp_path: Path) -> None:
    (tmp_path / "01.md").write_text(
        "---\ndocument_id: doc\ntitle: title\ntags: network\n---\nbody",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_knowledge_documents(tmp_path)


def test_empty_tag_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "01.md").write_text(
        "---\ndocument_id: doc\ntitle: title\ntags:\n  - '   '\n---\nbody",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_knowledge_documents(tmp_path)


def test_duplicate_tag_is_rejected(tmp_path: Path) -> None:
    _write_markdown(tmp_path / "01.md", tags=["dns", "dns"])

    with pytest.raises(ValidationError):
        load_knowledge_documents(tmp_path)


def test_root_wrong_type_is_rejected() -> None:
    with pytest.raises(TypeError):
        load_knowledge_documents(123)  # type: ignore[arg-type]


def test_missing_root_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_knowledge_documents(tmp_path / "missing")


def test_root_file_raises_not_a_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "knowledge.md"
    file_path.write_text("content", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        load_knowledge_documents(file_path)


def test_empty_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one .md"):
        load_knowledge_documents(tmp_path)


def test_real_knowledge_fixtures() -> None:
    documents = load_knowledge_documents(REAL_KNOWLEDGE_ROOT)

    assert len(documents) == 4
    assert [doc.document_id for doc in documents] == [
        "nm-basics",
        "dns-resolution",
        "service-diagnostics",
        "firewall-checks",
    ]
