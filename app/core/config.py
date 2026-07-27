"""Environment-driven application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """MemLink settings loaded from ``MEMLINK_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="MEMLINK_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "MemLink"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"
    metrics_dir: Path = Path("data") / "metrics"

    @field_validator("metrics_dir")
    @classmethod
    def resolve_metrics_dir(cls, value: Path) -> Path:
        """Resolve relative paths against the repository, not the shell cwd."""

        return value if value.is_absolute() else PROJECT_ROOT / value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """Normalize logging levels while rejecting unsupported values."""

        normalized = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return normalized


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings object."""

    return Settings()
