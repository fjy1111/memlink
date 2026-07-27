"""FastAPI integration tests."""

from pathlib import Path

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "MemLink",
        "version": "0.1.0",
    }


def test_run_and_fetch_task(client: TestClient, metrics_dir: Path) -> None:
    response = client.post(
        "/api/v1/tasks/run",
        json={
            "title": "企业技术故障分析",
            "prompt": "订单服务响应变慢，部分调用出现超时，请给出排查建议。",
        },
    )

    assert response.status_code == 201
    result = response.json()
    assert result["communication_mode"] == "text"
    assert result["metrics"]["message_count"] == 4
    assert len(result["messages"]) == 4
    assert list(metrics_dir.glob("*.json"))

    lookup = client.get(f"/api/v1/tasks/{result['task_id']}")
    assert lookup.status_code == 200
    assert lookup.json()["task"]["status"] == "completed"
    assert lookup.json()["result"]["task_id"] == result["task_id"]


def test_unknown_task_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/tasks/not-a-real-task")

    assert response.status_code == 404


def test_invalid_task_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tasks/run",
        json={"title": "bad", "prompt": "no"},
    )

    assert response.status_code == 422
