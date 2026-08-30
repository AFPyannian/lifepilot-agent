"""定义模型调用上下文与用量领域对象。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.credentials.models import ModelMode

UsageStatus = Literal["started", "succeeded", "failed"]


@dataclass(frozen=True)
class ModelInvocationContext:
    """一轮实际模型调用可审计的可信上下文。"""

    user_id: str
    request_id: str
    thread_id: str
    model_mode: ModelMode


@dataclass(frozen=True)
class UsageEvent:
    """一条模型调用事件，不保存消息正文或凭据。"""

    event_id: str
    request_id: str
    user_id: str
    thread_id: str
    provider: str
    model: str
    credential_mode: ModelMode
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    status: UsageStatus
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None


@dataclass(frozen=True)
class UsageSummary:
    """指定时间范围内的用户模型用量汇总。"""

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
