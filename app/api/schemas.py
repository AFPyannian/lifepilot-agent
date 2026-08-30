"""定义 LifePilot HTTP API 的请求和响应模型。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


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

    model_mode: Literal["BYOK", "PLATFORM"] = "PLATFORM"

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


class LoginRequest(BaseModel):
    """表示账号密码登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("username", mode="before")
    @classmethod
    def clean_username(cls, value: Any) -> Any:
        """清理登录用户名两端空白。"""
        if isinstance(value, str):
            return value.strip()
        return value


class CurrentUserResponse(BaseModel):
    """表示当前登录用户的公开信息。"""

    id: str
    username: str
    role: Literal["admin", "user"]
    status: Literal["active", "disabled"]


class LoginResponse(BaseModel):
    """表示登录成功后签发的 Session。"""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: CurrentUserResponse


class LogoutResponse(BaseModel):
    """表示 Session 注销结果。"""

    revoked: bool


class ChangePasswordRequest(BaseModel):
    """表示修改当前账号密码的请求。"""

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class RegistrationStatusResponse(BaseModel):
    """表示当前实例是否开放注册。"""

    mode: Literal["closed", "invite"]
    enabled: bool


class RegisterRequest(BaseModel):
    """表示邀请码注册请求。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=1024)
    invite_code: str = Field(min_length=16, max_length=256)

    @field_validator("username", "invite_code", mode="before")
    @classmethod
    def clean_text_fields(cls, value: Any) -> Any:
        """清理用户名和邀请码两端空白。"""
        if isinstance(value, str):
            return value.strip()
        return value


class CreateInvitationRequest(BaseModel):
    """表示管理员创建邀请码的请求。"""

    model_config = ConfigDict(extra="forbid")

    expires_in_hours: int = Field(default=72, ge=1, le=720)


class InvitationCreateResponse(BaseModel):
    """返回仅展示一次的邀请码原文。"""

    id: str
    invite_code: str
    expires_at: datetime


class InvitationItemResponse(BaseModel):
    """表示邀请码的公开管理状态。"""

    id: str
    created_by_username: str
    expires_at: datetime
    used_by_username: str | None
    used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class InvitationListResponse(BaseModel):
    """表示邀请码列表。"""

    invitations: list[InvitationItemResponse]


class InvitationRevokeResponse(BaseModel):
    """表示邀请码撤销结果。"""

    id: str
    revoked: bool


class ProviderCredentialUpsertRequest(BaseModel):
    """表示提交或轮换 DeepSeek API Key 的请求。"""

    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(min_length=1, max_length=1024)


class ProviderCredentialResponse(BaseModel):
    """只返回不含密文和指纹的凭据元数据。"""

    provider: Literal["deepseek"]
    masked_key: str
    status: Literal["active", "invalid", "revoked"]
    validated_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


class ModelAccessResponse(BaseModel):
    """表示当前账号可以使用的模型模式。"""

    byok_enabled: bool
    byok_configured: bool
    byok_status: Literal["active", "invalid", "revoked"] | None
    byok_allowed: bool
    byok_reason: str
    platform_enabled: bool
    platform_allowed: bool
    platform_reason: str
    default_mode: Literal["BYOK", "PLATFORM"] | None


class UsageEventResponse(BaseModel):
    """当前用户可见的单次模型调用事件。"""

    event_id: str
    request_id: str
    thread_id: str
    provider: Literal["deepseek"]
    model: str
    credential_mode: Literal["BYOK", "PLATFORM"]
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    status: Literal["started", "succeeded", "failed"]
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None


class UsageSummaryResponse(BaseModel):
    """当前用户在指定时间范围内的模型用量汇总。"""

    since: datetime
    until: datetime
    requests: int
    successful_calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    byok_calls: int
    platform_calls: int
