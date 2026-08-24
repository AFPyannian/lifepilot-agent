from typing import Any

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """Agent 对话请求。"""

    message: str = Field(
        min_length=1,
        max_length=10_000,
        description="用户发送给 Agent 的消息",
    )

    thread_id: str = Field(
        default="main",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="LangGraph 会话 ID",
    )

    @field_validator(
        "message",
        "thread_id",
        mode="before",
    )
    @classmethod
    def strip_text_fields(
        cls,
        value: Any,
    ) -> Any:
        if isinstance(value, str):
            return value.strip()

        return value


class ChatResponse(BaseModel):
    """Agent 对话响应。"""

    reply: str
    thread_id: str


class HealthResponse(BaseModel):
    """服务健康检查响应。"""

    status: str
    service: str


class KnowledgeDocumentResponse(BaseModel):
    """文档上传和导入结果。"""

    filename: str
    chunk_count: int
    already_indexed: bool


class KnowledgeDocumentItem(BaseModel):
    """知识库中的一个文档。"""

    filename: str
    chunk_count: int


class KnowledgeListResponse(BaseModel):
    """知识库文档列表。"""

    documents: list[KnowledgeDocumentItem]


class KnowledgeDeleteResponse(BaseModel):
    """知识库文档删除结果。"""

    filename: str
    deleted: bool