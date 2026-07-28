"""Environment-driven application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
    state_dir: Path = Path("data") / "states"
    memory_db_path: Path = Path("data") / "memory" / "memlink.db"
    enable_shared_memory: bool = True
    enable_semantic_state: bool = True
    enable_result_reference: bool = True

    llm_backend: str = "fake"
    deepseek_api_key: str = Field(default="", repr=False)
    deepseek_base_url: str = ""
    deepseek_model: str = ""
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_tokens: int = Field(default=1500, gt=0, le=8192)

    embedding_backend: str = "fake"
    embedding_api_key: str = Field(default="", repr=False)
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=32, gt=0, le=4096)
    embedding_timeout_seconds: float = Field(default=60.0, gt=0)
    embedding_max_retries: int = Field(default=2, ge=0, le=10)

    def deepseek_is_configured(self) -> bool:
        """Return whether all DeepSeek values are non-placeholder settings."""

        api_key = self.deepseek_api_key.strip()
        base_url = self.deepseek_base_url.strip()
        model = self.deepseek_model.strip()
        return (
            bool(api_key)
            and api_key != "replace-me"
            and base_url.startswith(("https://", "http://"))
            and not base_url.startswith("https://replace-with-")
            and not base_url.startswith("http://replace-with-")
            and bool(model)
            and not model.startswith("replace-with-")
        )

    @field_validator("metrics_dir", "state_dir", "memory_db_path")
    @classmethod
    def resolve_project_path(cls, value: Path) -> Path:
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

    @field_validator("llm_backend")
    @classmethod
    def validate_llm_backend(cls, value: str) -> str:
        """Restrict language models to the offline or DeepSeek adapter."""

        normalized = value.lower()
        allowed = {"fake", "deepseek"}
        if normalized not in allowed:
            raise ValueError(f"llm_backend must be one of {sorted(allowed)}")
        return normalized

    @field_validator("embedding_backend")
    @classmethod
    def validate_embedding_backend(cls, value: str) -> str:
        """Keep the existing optional OpenAI-compatible embedding adapter."""

        normalized = value.lower()
        allowed = {"fake", "openai_compatible"}
        if normalized not in allowed:
            raise ValueError(
                f"embedding_backend must be one of {sorted(allowed)}"
            )
        return normalized


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings object."""

    return Settings()
