"""FastAPI application factory for the AgentIPC Dashboard."""

from __future__ import annotations

from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from agentipc.dashboard.results import load_run_detail, scan_results
from agentipc.evaluation.io import read_raw_records
from agentipc.evaluation.metrics import MetricsSnapshot
from agentipc.evaluation.trace import TraceEvent


def create_app(
    results_dir: str | Path = "results",
    static_dir: str | Path | None = None,
) -> FastAPI:
    """Create a Dashboard application without scanning results at import time."""

    if not isinstance(results_dir, (str, Path)):
        raise TypeError("results_dir must be a str or Path")
    if static_dir is not None and not isinstance(static_dir, (str, Path)):
        raise TypeError("static_dir must be a str, Path, or None")

    results_root = Path(results_dir)
    app = FastAPI(title="AgentIPC Dashboard")

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "AgentIPC Dashboard", "status": "ok"}

    @app.get("/api/runs")
    def list_runs() -> dict[str, list[dict[str, object]]]:
        try:
            runs = scan_results(results_root)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="results repository unavailable") from exc
        return {"runs": [run.model_dump(mode="json") for run in runs]}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, object]:
        try:
            detail = load_run_detail(results_root, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="results repository unavailable") from exc

        if detail is None:
            raise HTTPException(status_code=404, detail="run not found")

        summary_payload = detail.summary.model_dump(mode="json")
        derived = summary_payload.pop("derived")
        return {
            "run_id": detail.run_id,
            "summary": summary_payload,
            "derived": derived,
            "environment": detail.environment.model_dump(mode="json"),
            "report": {
                "title": detail.report_title,
                "size_bytes": detail.report_bytes,
            },
        }

    @app.get("/api/runs/{run_id}/traces")
    def get_traces(run_id: str, task_id: str | None = None) -> dict[str, object]:
        try:
            detail = load_run_detail(results_root, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="trace repository unavailable") from exc

        if detail is None:
            raise HTTPException(status_code=404, detail="run not found")

        try:
            run_dir = _find_ready_run_dir(results_root, detail.run_id)
            if run_dir is None:
                raise HTTPException(status_code=404, detail="run not found")

            raw_path = run_dir / "raw.jsonl"
            if not raw_path.exists() and not raw_path.is_symlink():
                return {"run_id": detail.run_id, "traces": []}
            if raw_path.is_symlink() or not raw_path.is_file():
                raise ValueError("raw result is not a regular file")

            records = read_raw_records(raw_path)
            selected = [
                record
                for record in records
                if task_id is None or record.run_result.task_id == task_id
            ]
            if task_id is not None and not selected:
                raise HTTPException(status_code=404, detail="trace not found")

            traces = [
                _trace_entry(run_dir=run_dir, run_id=detail.run_id, record=record)
                for record in selected
            ]
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="trace repository unavailable") from exc

        return {"run_id": detail.run_id, "traces": traces}

    resolved_static_dir = _resolve_static_dir(static_dir)
    if resolved_static_dir is not None:
        app.mount(
            "/dashboard",
            StaticFiles(directory=resolved_static_dir, html=True),
            name="dashboard",
        )

    return app


def _resolve_static_dir(static_dir: str | Path | None) -> Path | None:
    if static_dir is not None:
        candidate = Path(static_dir)
        if not candidate.exists() or not candidate.is_dir():
            return None
        return candidate

    source_candidate = Path(__file__).resolve().parent / "static"
    if source_candidate.exists() and source_candidate.is_dir():
        return source_candidate

    installed_candidate = Path(sys.prefix) / "share" / "agentipc" / "dashboard"
    if installed_candidate.exists() and installed_candidate.is_dir():
        return installed_candidate

    return None


def _find_ready_run_dir(results_root: Path, run_id: str) -> Path | None:
    """Match an already validated run ID to a direct, non-symlink child."""

    if not results_root.exists() or not results_root.is_dir():
        return None

    for child in results_root.iterdir():
        if child.name != run_id:
            continue
        if child.is_symlink() or not child.is_dir():
            return None
        return child
    return None


def _trace_entry(*, run_dir: Path, run_id: str, record: object) -> dict[str, object]:
    run_result = record.run_result  # type: ignore[attr-defined]
    metrics = MetricsSnapshot.model_validate(run_result.metrics)
    trace_path = run_result.trace_path

    status, reason, events = _load_trace_events(
        run_dir=run_dir,
        run_id=run_id,
        stored_path=trace_path,
    )

    return {
        "task_id": run_result.task_id,
        "experiment": record.experiment.name.value,  # type: ignore[attr-defined]
        "seed": record.seed,  # type: ignore[attr-defined]
        "success": run_result.success,
        "trace_status": status,
        "reason": reason,
        "metrics": metrics.model_dump(mode="json"),
        "events": events,
    }


def _load_trace_events(
    *,
    run_dir: Path,
    run_id: str,
    stored_path: str | None,
) -> tuple[str, str | None, list[dict[str, object]]]:
    if stored_path is None or stored_path == "":
        return "missing", "trace file missing", []

    trace_path = _safe_trace_path(run_dir=run_dir, run_id=run_id, stored_path=stored_path)
    if trace_path is None:
        return "invalid", "trace data invalid", []

    if not trace_path.exists():
        return "missing", "trace file missing", []
    if trace_path.is_symlink() or not trace_path.is_file():
        return "invalid", "trace data invalid", []

    events: list[dict[str, object]] = []
    try:
        with trace_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                stripped = line.strip()
                if not stripped:
                    continue
                event = TraceEvent.model_validate_json(stripped)
                events.append(event.model_dump(mode="json"))
    except Exception:
        return "invalid", "trace data invalid", []

    return "ready", None, events


def _safe_trace_path(*, run_dir: Path, run_id: str, stored_path: str) -> Path | None:
    """Relocate a stored trace path into the selected run without trusting its root."""

    if "\x00" in stored_path:
        return None

    normalized = stored_path.replace("\\", "/")
    if normalized == "" or "//" in normalized.lstrip("/"):
        return None

    parts = normalized.split("/")
    while parts and parts[0] == "":
        parts.pop(0)

    if run_id in parts:
        suffix = parts[parts.index(run_id) + 1 :]
    else:
        is_windows_absolute = bool(parts and len(parts[0]) == 2 and parts[0][1] == ":")
        if normalized.startswith("/") or is_windows_absolute:
            return None
        suffix = parts

    if not suffix or any(part in {"", ".", ".."} for part in suffix):
        return None

    candidate = run_dir.joinpath(*suffix)
    current = run_dir
    for part in suffix:
        current = current / part
        try:
            if current.is_symlink():
                return None
        except OSError:
            return None

    try:
        resolved_root = run_dir.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=False)
        relative = resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return None

    if str(relative) in {"", "."}:
        return None
    return resolved_candidate
