"""Small process-local task repository for the stage-one MVP."""

import asyncio

from app.models.domain import TaskRecord


class TaskStore:
    """Concurrency-safe in-memory storage used by POST and GET endpoints."""

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()

    async def save(self, record: TaskRecord) -> None:
        """Insert or replace a task record."""

        async with self._lock:
            self._records[record.task.task_id] = record.model_copy(deep=True)

    async def get(self, task_id: str) -> TaskRecord | None:
        """Return a defensive copy of a task record."""

        async with self._lock:
            record = self._records.get(task_id)
            return record.model_copy(deep=True) if record is not None else None
