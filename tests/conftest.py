"""Shared test fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def metrics_dir(tmp_path: Path) -> Path:
    """Return an isolated metric directory."""

    return tmp_path / "metrics"


@pytest.fixture
def client(metrics_dir: Path) -> Iterator[TestClient]:
    """Create a fresh API and task store for every test."""

    settings = Settings(
        environment="test",
        log_level="WARNING",
        metrics_dir=metrics_dir,
        state_dir=metrics_dir.parent / "states",
        memory_db_path=metrics_dir.parent / "memory" / "test.db",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
