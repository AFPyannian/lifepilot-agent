"""集中定义、校验并加载 LifePilot 运行配置。"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.exceptions import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """保存经过 Pydantic 校验的应用配置。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    deepseek_api_key: SecretStr

    deepseek_model: str = Field(default="deepseek-v4-flash", min_length=1)

    deepseek_timeout_seconds: float = Field(default=60.0, gt=0)
    deepseek_max_retries: int = Field(default=2, ge=0, le=10)

    api_rate_limit_enabled: bool = True
    api_rate_limit_requests: int = Field(default=60, gt=0)
    api_rate_limit_window_seconds: int = Field(default=60, gt=0)

    agent_recursion_limit: int = Field(default=25, ge=5, le=100)

    local_cli_owner_id: str = Field(default="local-user", min_length=1)
    default_thread_id: str = Field(default="main", min_length=1)

    auth_session_ttl_hours: int = Field(default=168, ge=1, le=24 * 90)
    auth_session_touch_interval_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
    )
    auth_login_max_failures: int = Field(default=5, ge=1, le=20)
    auth_login_window_seconds: int = Field(default=900, ge=60, le=86_400)
    registration_mode: Literal["closed", "invite"] = "closed"
    auth_registration_max_failures: int = Field(default=10, ge=1, le=50)
    auth_registration_window_seconds: int = Field(
        default=900,
        ge=60,
        le=86_400,
    )
    auth_invitation_max_ttl_hours: int = Field(
        default=720,
        ge=1,
        le=720,
    )

    app_database_path: Path = PROJECT_ROOT / "data" / "lifepilot.db"

    checkpoint_database_path: Path = PROJECT_ROOT / "data" / "checkpoints.db"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    log_file_path: Path = PROJECT_ROOT / "logs" / "lifepilot.log"
    log_max_bytes: int = Field(default=1_000_000, gt=0)
    log_backup_count: int = Field(default=3, ge=1)

    app_environment: Literal["development", "test", "production"] = "development"

    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "lifepilot-development"
    langsmith_endpoint: str = "https://apac.api.smith.langchain.com"
    langsmith_workspace_id: str | None = None

    langsmith_hide_inputs: bool = False
    langsmith_hide_outputs: bool = False

    langgraph_strict_msgpack: bool = True

    knowledge_source_directory: Path = PROJECT_ROOT / "knowledge_base"

    chroma_persist_directory: Path = PROJECT_ROOT / "data" / "chroma"

    embedding_model_name: str = "models/bge-small-zh-v1.5"

    embedding_device: Literal["cpu", "cuda"] = "cpu"

    knowledge_chunk_size: int = Field(default=700, gt=0)

    knowledge_chunk_overlap: int = Field(default=120, ge=0)

    knowledge_retrieval_k: int = Field(default=4, gt=0)

    knowledge_max_file_bytes: int = Field(default=20_000_000, gt=0)

    @field_validator(
        "log_level",
        mode="before",
    )
    @classmethod
    def normalize_log_level(
        cls,
        value: object,
    ) -> str:
        """将日志级别规范化为大写形式。"""
        return str(value).upper()

    @field_validator(
        "app_database_path",
        "checkpoint_database_path",
        "log_file_path",
        "knowledge_source_directory",
        "chroma_persist_directory",
        mode="after",
    )
    @classmethod
    def resolve_project_path(cls, value: Path) -> Path:
        """将相对路径解析为项目根目录下的绝对路径。"""
        if value.is_absolute():
            return value

        return (PROJECT_ROOT / value).resolve()

    @field_validator(
        "embedding_model_name",
        mode="after",
    )
    @classmethod
    def resolve_embedding_model_path(cls, value: str) -> str:
        """将本地 Embedding 模型路径解析为绝对路径。"""
        model_path = Path(value).expanduser()

        if not model_path.is_absolute():
            model_path = PROJECT_ROOT / model_path

        return str(model_path.resolve())

    @model_validator(mode="after")
    def validate_knowledge_chunking(self) -> "Settings":
        """确保文本块重叠长度小于文本块长度。"""
        if self.knowledge_chunk_overlap >= self.knowledge_chunk_size:
            raise ValueError("knowledge_chunk_overlap 必须小于 knowledge_chunk_size")

        return self

    @model_validator(mode="after")
    def validate_langsmith(self) -> "Settings":
        """确保启用 LangSmith 时同时提供有效配置。"""

        api_key = ""

        if self.langsmith_api_key is not None:
            api_key = self.langsmith_api_key.get_secret_value().strip()

        if self.langsmith_tracing and not api_key:
            raise ValueError("启用LangSmith追踪时必须配置 LANGSMITH_API_KEY")

        if self.langsmith_tracing and not self.langsmith_project.strip():
            raise ValueError("启用LangSmith追踪时项目名称不能为空")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存全局应用配置。"""
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        raise ConfigurationError("Application settings validation failed.") from error


def apply_runtime_environment(settings: Settings) -> None:
    """向依赖库写入必须的进程级运行参数。"""
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = (
        "true" if settings.langgraph_strict_msgpack else "false"
    )
