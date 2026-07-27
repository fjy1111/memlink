"""API mode switching tests."""

from fastapi.testclient import TestClient


def test_api_runs_structured_mode(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tasks/run",
        json={
            "title": "结构化 RAG 故障分析",
            "prompt": "RAG 检索正常但生成阶段延迟升高。",
            "task_topic": "enterprise-rag",
            "mode": "structured",
            "llm_backend": "fake",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["communication_mode"] == "structured"
    assert body["protocol_messages"]
    assert body["metrics"]["msgpack_serialized_bytes"] > 0
    assert body["metrics"]["semantic_state_transfer_count"] > 0

    lookup = client.get(f"/api/v1/tasks/{body['task_id']}")
    assert lookup.status_code == 200
    assert lookup.json()["result"]["communication_mode"] == "structured"


def test_api_defaults_to_stage_one_text_mode(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tasks/run",
        json={
            "title": "文本模式回归",
            "prompt": "API 返回 500，请分析故障。",
        },
    )

    assert response.status_code == 201
    assert response.json()["communication_mode"] == "text"
