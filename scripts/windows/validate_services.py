"""Start, probe, and stop MemLink services with the current Python."""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Perform one local JSON request using the standard library."""

    data = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def wait_for_url(url: str, process: subprocess.Popen[bytes]) -> int:
    """Wait until a local service is healthy or exits."""

    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError(
                f"Service exited early with code {process.returncode}"
            )
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    raise TimeoutError(f"Service did not become ready: {url}")


def run_service(
    arguments: list[str],
    *,
    health_url: str,
    verify: Any,
) -> dict[str, Any]:
    """Run fixed Python module arguments and always stop that exact process."""

    creation_flags = (
        subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )
    process = subprocess.Popen(
        [sys.executable, *arguments],
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    try:
        health_status = wait_for_url(health_url, process)
        result = verify()
        return {
            "pid": process.pid,
            "health_status": health_status,
            **result,
        }
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def validate_streamlit() -> dict[str, Any]:
    """Validate Streamlit's real health endpoint."""

    return run_service(
        [
            "-m",
            "streamlit",
            "run",
            "app/ui/streamlit_app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            "8501",
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        health_url="http://127.0.0.1:8501/_stcore/health",
        verify=lambda: {"page_url": "http://127.0.0.1:8501"},
    )


def validate_api() -> dict[str, Any]:
    """Validate health, run, and lookup against a real Uvicorn process."""

    def verify() -> dict[str, Any]:
        health_status, health = request_json("http://127.0.0.1:8000/health")
        run_status, result = request_json(
            "http://127.0.0.1:8000/api/v1/tasks/run",
            method="POST",
            payload={
                "title": "阶段四 API 验证",
                "prompt": "生产 API 返回 500，请使用离线模式给出排查方案。",
                "task_topic": "phase-four-validation",
                "mode": "structured",
                "llm_backend": "fake",
            },
        )
        lookup_status, lookup = request_json(
            "http://127.0.0.1:8000/api/v1/tasks/"
            + result["task_id"]
        )
        return {
            "health_endpoint_status": health_status,
            "health_body": health,
            "run_status": run_status,
            "task_id": result["task_id"],
            "task_mode": result["communication_mode"],
            "lookup_status": lookup_status,
            "lookup_task_status": lookup["task"]["status"],
        }

    return run_service(
        [
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        health_url="http://127.0.0.1:8000/health",
        verify=verify,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--service",
        choices=["streamlit", "api", "all"],
        default="all",
    )
    arguments = parser.parse_args()
    results: dict[str, Any] = {}
    if arguments.service in {"streamlit", "all"}:
        results["streamlit"] = validate_streamlit()
    if arguments.service in {"api", "all"}:
        results["api"] = validate_api()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

