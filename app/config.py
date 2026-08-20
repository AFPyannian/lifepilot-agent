import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import (
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

from app.exceptions import ConfigurationError

# 计算项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Validated application configuration."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    deepseek_api_key: SecretStr

    deepseek_model: str = Field(
        default="deepseek-v4-flash",
        min_length=1,
    )

    owner_id: str = Field(
        default="local-user",
        min_length=1,
    )

    default_thread_id: str = Field(
        default="main",
        min_length=1,
    )

    app_database_path: Path = (
        PROJECT_ROOT
        / "data"
        / "lifepilot.db"
    )

    checkpoint_database_path: Path = (
        PROJECT_ROOT
        / "data"
        / "checkpoints.db"
    )

    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    log_file_path: Path = (
        PROJECT_ROOT
        / "logs"
        / "lifepilot.log"
    )

    log_max_bytes: int = Field(
        default=1_000_000,
        gt=0,
    )

    log_backup_count: int = Field(
        default=3,
        ge=1,
    )

    langgraph_strict_msgpack: bool = True

    @field_validator(
        "log_level",
        mode="before",
    )
    @classmethod
    def normalize_log_level(
        cls,
        value,
    ) -> str:
        """Normalize log levels such as info to INFO."""
        return str(value).upper()

    @field_validator(
        "app_database_path",
        "checkpoint_database_path",
        "log_file_path",
        mode="after",
    )
    @classmethod
    def resolve_project_path(
        cls,
        value: Path,
    ) -> Path:
        """Resolve relative paths from the project root."""
        if value.is_absolute():
            return value

        return (
            PROJECT_ROOT
            / value
        ).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache validated application settings."""
    try:
        return Settings()
    except ValidationError as error:
        raise ConfigurationError(
            "Application settings validation failed."
        ) from error


def apply_runtime_environment(
    settings: Settings,
) -> None:
    """Export settings required by third-party libraries."""
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = (
        "true"
        if settings.langgraph_strict_msgpack
        else "false"
    )