from typing import Any, Literal
from datetime import datetime

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


class ApprovalDecision(BaseModel):
    """批准或拒绝一个中断操作。"""

    thread_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )

    approved: bool


class ApprovalResumeResponse(BaseModel):
    """恢复执行后的结果。"""

    status: Literal[
        "completed",
        "approval_required",
    ]

    thread_id: str
    reply: str | None = None

    approval_request: (
        dict[str, Any] | None
    ) = None

class ConversationSummary(BaseModel):
    """会话列表中的摘要。"""

    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    """历史会话列表。"""

    conversations: list[
        ConversationSummary
    ]


class ConversationMessage(BaseModel):
    """前端可以显示的一条消息。"""

    role: Literal[
        "user",
        "assistant",
    ]

    content: str


class ConversationDetailResponse(BaseModel):
    """会话消息及待审批状态。"""

    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime

    messages: list[
        ConversationMessage
    ]

    pending_approval: (
        dict[str, Any] | None
    ) = None


class RenameConversationRequest(BaseModel):
    """修改会话标题。"""

    title: str = Field(
        min_length=1,
        max_length=80,
    )

    @field_validator(
        "title",
        mode="before",
    )
    @classmethod
    def clean_title(
        cls,
        value: Any,
    ) -> Any:
        if not isinstance(value, str):
            return value

        clean_value = " ".join(
            value.split()
        )

        if not clean_value:
            raise ValueError(
                "标题不能为空"
            )

        return clean_value


class DeleteConversationResponse(BaseModel):
    """删除会话结果。"""

    thread_id: str
    deleted: bool