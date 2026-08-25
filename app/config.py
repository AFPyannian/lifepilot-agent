import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.exceptions import ConfigurationError

# 计算项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """经过校验的应用配置"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # DeepSeek模型的API Key配置
    deepseek_api_key: SecretStr
    # DeepSeek模型的名称
    deepseek_model: str = Field(default="deepseek-v4-flash", min_length=1)

    # 当前用户和默认会话
    owner_id: str = Field(default="local-user", min_length=1)
    default_thread_id: str = Field(default="main", min_length=1)

    # 业务数据库
    app_database_path: Path = (PROJECT_ROOT / "data" / "lifepilot.db")
    # 会话数据库
    checkpoint_database_path: Path = (PROJECT_ROOT / "data" / "checkpoints.db")

    # 日志配置
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    log_file_path: Path = (PROJECT_ROOT / "logs" / "lifepilot.log")
    log_max_bytes: int = Field(default=1_000_000, gt=0)
    log_backup_count: int = Field(default=3, ge=1)

    # 应用运行环境
    app_environment: Literal["development", "test", "production"] = "development"

    # LangSmith可观测性
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "lifepilot-development"
    langsmith_endpoint: str = "https://apac.api.smith.langchain.com"
    langsmith_workspace_id: str | None = None

    # 开启后只记录结构、耗时等信息，不上传输入或输出正文。
    langsmith_hide_inputs: bool = False
    langsmith_hide_outputs: bool = False

    # LangGraph配置
    langgraph_strict_msgpack: bool = True

    # 原始文档保存目录
    knowledge_source_directory: Path = (PROJECT_ROOT / "knowledge_base")
    # Chroma向量数据库保存目录
    chroma_persist_directory: Path = (PROJECT_ROOT / "data" / "chroma")

    # 中文Embedding模型
    embedding_model_name: str = "models/bge-small-zh-v1.5"
    # 运行Embedding模型的设备
    embedding_device: Literal["cpu", "cuda"] = "cpu"

    # 每个文本块的最大字符数
    knowledge_chunk_size: int = Field(default=700, gt=0)
    # 相邻文本块之间重复保留的字符数
    knowledge_chunk_overlap: int = Field(default=120, ge=0)
    # 每次检索返回几个片段
    knowledge_retrieval_k: int = Field(default=4, gt=0)
    # 单个知识库文件最大20MB
    knowledge_max_file_bytes: int = Field(default=20_000_000, gt=0)

    @field_validator(
        "log_level",
        mode="before",
    )
    @classmethod
    def normalize_log_level(cls, value) -> str:
        """把info等配置统一转换成INFO"""
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
        """将相对路径转换为基于项目根目录的绝对路径"""
        if value.is_absolute():
            return value

        return (PROJECT_ROOT / value).resolve()

    @field_validator(
        "embedding_model_name",
        mode="after",
    )
    @classmethod
    def resolve_embedding_model_path(cls, value: str) -> str:
        """将Embedding模型的相对路径转换为绝对路径"""
        model_path = Path(value).expanduser()

        if not model_path.is_absolute():
            model_path = PROJECT_ROOT / model_path

        return str(model_path.resolve())

    @model_validator(mode="after")
    def validate_knowledge_chunking(self) -> "Settings":
        """确保文本块重叠长度小于文本块总长度。"""
        if self.knowledge_chunk_overlap >= self.knowledge_chunk_size:
            raise ValueError(
                "knowledge_chunk_overlap 必须小于 knowledge_chunk_size"
            )

        return self

    @model_validator(mode="after")
    def validate_langsmith(self) -> "Settings":
        """校验LangSmith配置。"""

        api_key = ""

        if self.langsmith_api_key is not None:
            api_key = (
                self.langsmith_api_key
                .get_secret_value()
                .strip()
            )

        if self.langsmith_tracing and not api_key:
            raise ValueError(
                "启用LangSmith追踪时必须配置 LANGSMITH_API_KEY"
            )

        if self.langsmith_tracing and not self.langsmith_project.strip():
            raise ValueError(
                "启用LangSmith追踪时项目名称不能为空"
            )

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存应用配置"""
    try:
        return Settings()
    except ValidationError as error:
        raise ConfigurationError(
            "Application settings validation failed."
        ) from error


def apply_runtime_environment(settings: Settings) -> None:
    """向第三方库导出运行时配置"""
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = (
        "true"
        if settings.langgraph_strict_msgpack
        else "false"
    )