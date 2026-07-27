"""Metadata for real non-text semantic state."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.domain import utc_now


class SemanticState(BaseModel):
    """Validated metadata referencing a binary NumPy vector."""

    state_id: str
    task_id: str
    source_agent: str
    semantic_type: str
    dimensions: int = Field(gt=0)
    dtype: str
    byte_size: int = Field(gt=0)
    storage_ref: str
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class StateStoreStats(BaseModel):
    """State access counters consumed by run metrics."""

    created_count: int = 0
    read_count: int = 0
    transfer_count: int = 0
    transferred_bytes: int = 0
