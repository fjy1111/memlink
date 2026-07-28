"""Offline tests for Streamlit services, presenters, and page startup."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.models import CommunicationMode
from app.ui.presenter import (
    benchmark_table_rows,
    build_agent_cards,
    build_memory_rows,
    build_semantic_state_rows,
)
from app.ui.service import (
    build_orchestrator,
    deepseek_backend_is_configured,
    load_benchmark_results,
    run_task,
)


def ui_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        metrics_dir=tmp_path / "metrics",
        state_dir=tmp_path / "states",
        memory_db_path=tmp_path / "memory" / "shared.db",
        llm_backend="fake",
        embedding_backend="fake",
    )


def test_deepseek_backend_is_never_enabled_without_environment_credentials(
    tmp_path: Path,
) -> None:
    settings = ui_settings(tmp_path)

    assert deepseek_backend_is_configured(settings) is False
    with pytest.raises(ValueError, match="配置不完整"):
        build_orchestrator(
            settings,
            backend="deepseek",
            enable_shared_memory=True,
            enable_semantic_state=True,
            enable_result_reference=True,
        )

    placeholder_settings = settings.model_copy(
        update={
            "deepseek_api_key": "replace-me",
            "deepseek_base_url": "replace-with-deepseek-base-url",
            "deepseek_model": "replace-with-model-name",
        }
    )
    assert deepseek_backend_is_configured(placeholder_settings) is False


def test_ui_can_build_deepseek_with_fake_embedding(tmp_path: Path) -> None:
    settings = ui_settings(tmp_path).model_copy(
        update={
            "deepseek_api_key": "test-only-secret",
            "deepseek_base_url": "https://example.invalid/v1",
            "deepseek_model": "test-model",
        }
    )

    orchestrator = build_orchestrator(
        settings,
        backend="deepseek",
        enable_shared_memory=True,
        enable_semantic_state=True,
        enable_result_reference=True,
    )

    assert deepseek_backend_is_configured(settings) is True
    assert orchestrator._backend_name == "deepseek"
    assert orchestrator._embedding.__class__.__name__ == "FakeEmbeddingClient"


@pytest.mark.asyncio
async def test_presenter_uses_real_trace_memory_state_and_review(
    tmp_path: Path,
) -> None:
    orchestrator = build_orchestrator(
        ui_settings(tmp_path),
        backend="fake",
        enable_shared_memory=True,
        enable_semantic_state=True,
        enable_result_reference=True,
    )
    await run_task(
        orchestrator,
        title="RAG 响应变慢",
        prompt="RAG 服务响应变慢，需要定位检索和生成瓶颈。",
        task_topic="enterprise-rag",
        mode=CommunicationMode.STRUCTURED,
    )
    result = await run_task(
        orchestrator,
        title="RAG 高并发超时",
        prompt="高并发下 RAG 请求超时，请复用前序故障经验。",
        task_topic="enterprise-rag",
        mode=CommunicationMode.STRUCTURED,
    )

    cards = build_agent_cards(result, orchestrator)
    memories = build_memory_rows(result, orchestrator)
    states = build_semantic_state_rows(result, orchestrator)

    assert [card["role"] for card in cards] == [
        "planner",
        "retriever",
        "executor",
        "reviewer",
    ]
    assert all(card["capabilities"] for card in cards)
    assert all(card["status"] == "completed" for card in cards)
    assert memories
    assert {
        "memory_id",
        "memory_type",
        "summary",
        "usage_count",
        "confidence",
    } == set(memories[0])
    assert states
    assert {
        "state_id",
        "dimensions",
        "dtype",
        "byte_size",
        "source_agent",
        "semantic_type",
        "content_hash",
    } == set(states[0])
    assert "vector" not in json.dumps(states)
    assert result.review_passed is True
    assert result.review_confidence == pytest.approx(0.9)
    assert result.evidence_ids


def test_benchmark_loader_handles_missing_and_real_files(tmp_path: Path) -> None:
    assert load_benchmark_results(tmp_path / "missing") is None

    results = tmp_path / "results"
    results.mkdir()
    summary = [
        {
            "experiment_name": "text",
            "run_count": 1,
            "completion_rate": 1.0,
            "average_memory_hit_rate": 0.0,
            "metrics": {
                name: {"mean": value, "p50": value, "p95": value}
                for name, value in {
                    "text_character_count": 100,
                    "estimated_token_count": 25,
                    "json_serialized_bytes": 120,
                    "msgpack_serialized_bytes": 0,
                    "total_duration_ms": 5,
                }.items()
            },
        }
    ]
    (results / "benchmark_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )
    (results / "stability_summary.json").write_text(
        json.dumps({"total_tasks": 1}),
        encoding="utf-8",
    )

    payload = load_benchmark_results(results)

    assert payload is not None
    rows = benchmark_table_rows(payload["summary"])
    assert rows[0]["experiment"] == "text"
    assert rows[0]["tokens"] == 25


def test_streamlit_page_runs_fake_task_without_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMLINK_LLM_BACKEND", "fake")
    monkeypatch.setenv("MEMLINK_EMBEDDING_BACKEND", "fake")
    monkeypatch.setenv("MEMLINK_METRICS_DIR", str(tmp_path / "metrics"))
    monkeypatch.setenv("MEMLINK_STATE_DIR", str(tmp_path / "states"))
    monkeypatch.setenv(
        "MEMLINK_MEMORY_DB_PATH",
        str(tmp_path / "memory" / "shared.db"),
    )
    get_settings.cache_clear()
    page = PROJECT_ROOT / "app" / "ui" / "streamlit_app.py"

    app = AppTest.from_file(str(page)).run(timeout=30)

    assert not app.exception
    assert app.title[0].value == "MemLink"
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert app.success
    source = page.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "settings.deepseek_api_key" in source
    assert "st.write(settings.deepseek_api_key)" not in source
    assert 'st.session_state["deepseek_api_key"]' not in source
    assert "MEMLINK_DEEPSEEK_API_KEY" not in source
    get_settings.cache_clear()
