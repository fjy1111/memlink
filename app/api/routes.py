"""Stage-one HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import Settings
from app.core.logging import get_logger
from app.models.domain import HealthResponse, TaskCreate, TaskRecord, TaskResult
from app.runtime.orchestrator import OrchestrationError, TextTaskOrchestrator

logger = get_logger(__name__)
router = APIRouter()


def get_orchestrator(request: Request) -> TextTaskOrchestrator:
    """Return the application-scoped orchestrator."""

    return request.app.state.orchestrator


OrchestratorDependency = Annotated[
    TextTaskOrchestrator, Depends(get_orchestrator)
]


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health(request: Request) -> HealthResponse:
    """Report whether the API process is ready to accept tasks."""

    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.post(
    "/api/v1/tasks/run",
    response_model=TaskResult,
    status_code=status.HTTP_201_CREATED,
    tags=["tasks"],
)
async def run_task(
    task_create: TaskCreate,
    orchestrator: OrchestratorDependency,
) -> TaskResult:
    """Run a task through Planner, Retriever, Executor, and Reviewer."""

    try:
        return await orchestrator.run(task_create)
    except OrchestrationError as exc:
        logger.exception("Task orchestration failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get(
    "/api/v1/tasks/{task_id}",
    response_model=TaskRecord,
    tags=["tasks"],
)
async def get_task(
    task_id: str,
    orchestrator: OrchestratorDependency,
) -> TaskRecord:
    """Fetch the current state and result for a previously submitted task."""

    record = await orchestrator.get_task(task_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id!r} was not found",
        )
    return record
