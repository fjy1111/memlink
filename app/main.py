"""FastAPI application factory and default application instance."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.runtime.orchestrator import TaskOrchestrator

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated application instance.

    Supplying settings is useful for tests because metrics can be redirected to
    a temporary directory without changing process-wide environment variables.
    """

    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        active_settings.metrics_dir.mkdir(parents=True, exist_ok=True)
        active_settings.state_dir.mkdir(parents=True, exist_ok=True)
        active_settings.memory_db_path.parent.mkdir(parents=True, exist_ok=True)
        application.state.orchestrator = TaskOrchestrator.from_settings(
            active_settings
        )
        logger.info(
            "Starting %s %s in %s mode",
            active_settings.app_name,
            active_settings.app_version,
            active_settings.environment,
        )
        yield
        logger.info("Stopping %s", active_settings.app_name)

    application = FastAPI(
        title=active_settings.app_name,
        version=active_settings.app_version,
        description="MemLink dual-mode multi-agent collaboration infrastructure",
        lifespan=lifespan,
    )
    application.state.settings = active_settings
    application.state.orchestrator = None
    application.include_router(router)
    return application


app = create_app()
