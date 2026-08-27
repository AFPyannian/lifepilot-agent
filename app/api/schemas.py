"""定义 LifePilot HTTP API 的请求和响应模型。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """表示一轮 Agent 对话请求。"""

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
        """清理消息和会话标识两端的空白。"""
        if isinstance(value, str):
            return value.strip()

        return value


class ChatResponse(BaseModel):
    """表示一轮同步 Agent 对话结果。"""

    reply: str
    thread_id: str


class HealthResponse(BaseModel):
    """表示服务健康状态。"""

    status: str
    service: str


class KnowledgeDocumentResponse(BaseModel):
    """表示知识文档导入结果。"""

    filename: str
    chunk_count: int
    already_indexed: bool


class KnowledgeDocumentItem(BaseModel):
    """表示知识库中的一份文档摘要。"""

    filename: str
    chunk_count: int


class KnowledgeListResponse(BaseModel):
    """表示知识文档列表。"""

    documents: list[KnowledgeDocumentItem]


class KnowledgeDeleteResponse(BaseModel):
    """表示知识文档删除结果。"""

    filename: str
    deleted: bool


class ApprovalDecision(BaseModel):
    """表示用户对待审批操作的决定。"""

    thread_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )

    approved: bool


class ApprovalResumeResponse(BaseModel):
    """表示审批恢复后的执行状态。"""

    status: Literal[
        "completed",
        "approval_required",
    ]

    thread_id: str
    reply: str | None = None

    approval_request: dict[str, Any] | None = None


class ConversationSummary(BaseModel):
    """表示历史会话列表中的摘要。"""

    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    """表示历史会话列表。"""

    conversations: list[ConversationSummary]


class ConversationMessage(BaseModel):
    """表示前端可展示的一条会话消息。"""

    role: Literal[
        "user",
        "assistant",
    ]

    content: str


class ConversationDetailResponse(BaseModel):
    """表示会话消息及其待审批状态。"""

    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime

    messages: list[ConversationMessage]

    pending_approval: dict[str, Any] | None = None


class RenameConversationRequest(BaseModel):
    """表示会话重命名请求。"""

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
        """去除标题两端空白并拒绝空标题。"""
        if not isinstance(value, str):
            return value

        clean_value = " ".join(value.split())

        if not clean_value:
            raise ValueError("标题不能为空")

        return clean_value


class DeleteConversationResponse(BaseModel):
    """表示历史会话删除结果。"""

    thread_id: str
    deleted: bool
