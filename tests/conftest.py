"""Shared test fixtures."""

import os
import socket
from collections.abc import Iterator
from ipaddress import ip_address
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Test collection imports ``app.main``, whose module-level application normally
# loads the repository .env. Disable that source before importing app.main so a
# developer's local credentials can never enter the pytest process.
from app.core.config import Settings, get_settings

Settings.model_config["env_file"] = None
os.environ["MEMLINK_LLM_BACKEND"] = "fake"
os.environ["MEMLINK_DEEPSEEK_API_KEY"] = ""
os.environ["MEMLINK_DEEPSEEK_BASE_URL"] = ""
os.environ["MEMLINK_DEEPSEEK_MODEL"] = ""
os.environ["MEMLINK_EMBEDDING_BACKEND"] = "fake"
os.environ["MEMLINK_EMBEDDING_API_KEY"] = ""
get_settings.cache_clear()

from app.main import create_app


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow test infrastructure loopback sockets but block the internet."""

    original_connect = socket.socket.connect

    def guarded_connect(
        client_socket: socket.socket,
        address: object,
    ) -> object:
        if not isinstance(address, tuple):
            return original_connect(client_socket, address)
        host = str(address[0])
        try:
            is_loopback = ip_address(host).is_loopback
        except ValueError:
            is_loopback = host.lower() == "localhost"
        if not is_loopback:
            raise AssertionError(
                "Tests must use Fake clients, MockTransport, or "
                "loopback-only services"
            )
        return original_connect(client_socket, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
def metrics_dir(tmp_path: Path) -> Path:
    """Return an isolated metric directory."""

    return tmp_path / "metrics"


@pytest.fixture
def client(metrics_dir: Path) -> Iterator[TestClient]:
    """Create a fresh API and task store for every test."""

    settings = Settings(
        _env_file=None,
        environment="test",
        log_level="WARNING",
        metrics_dir=metrics_dir,
        state_dir=metrics_dir.parent / "states",
        memory_db_path=metrics_dir.parent / "memory" / "test.db",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
