"""围绕实际模型调用记录开始、成功和失败事件。"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.repositories.usage_repository import UsageRepository
from app.usage.models import ModelInvocationContext, UsageEvent


class UsageTracker:
    """将模型响应中的可选 token 元数据写入事件仓储。"""

    def __init__(self, repository: UsageRepository) -> None:
        self._repository = repository

    def start(self, *, context: ModelInvocationContext, model: str) -> UsageEvent:
        event = UsageEvent(
            event_id=str(uuid4()),
            request_id=context.request_id,
            user_id=context.user_id,
            thread_id=context.thread_id,
            provider="deepseek",
            model=model,
            credential_mode=context.model_mode,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            status="started",
            error_code=None,
            started_at=datetime.now(UTC),
            completed_at=None,
            duration_ms=None,
        )
        if not self._repository.begin(event):
            raise RuntimeError("无法创建模型用量事件。")
        return event

    def succeed(self, event: UsageEvent, response: Any) -> bool:
        input_tokens, output_tokens, total_tokens = self._extract_tokens(response)
        completed_at = datetime.now(UTC)
        return self._repository.mark_succeeded(
            event_id=event.event_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            completed_at=completed_at,
            duration_ms=self._duration_ms(event.started_at, completed_at),
        )

    def fail(self, event: UsageEvent, error_code: str) -> bool:
        completed_at = datetime.now(UTC)
        return self._repository.mark_failed(
            event_id=event.event_id,
            error_code=error_code,
            completed_at=completed_at,
            duration_ms=self._duration_ms(event.started_at, completed_at),
        )

    @staticmethod
    def _extract_tokens(response: Any) -> tuple[int | None, int | None, int | None]:
        usage = getattr(response, "usage_metadata", None)
        if not isinstance(usage, dict):
            response_metadata = getattr(response, "response_metadata", {})
            usage = (
                response_metadata.get("token_usage", {})
                if isinstance(response_metadata, dict)
                else {}
            )
        if not isinstance(usage, dict):
            return None, None, None
        input_tokens = UsageTracker._optional_int(
            usage.get("input_tokens", usage.get("prompt_tokens"))
        )
        output_tokens = UsageTracker._optional_int(
            usage.get("output_tokens", usage.get("completion_tokens"))
        )
        total_tokens = UsageTracker._optional_int(usage.get("total_tokens"))
        if (
            total_tokens is None
            and input_tokens is not None
            and output_tokens is not None
        ):
            total_tokens = input_tokens + output_tokens
        return input_tokens, output_tokens, total_tokens

    @staticmethod
    def _optional_int(value: object) -> int | None:
        return value if isinstance(value, int) and value >= 0 else None

    @staticmethod
    def _duration_ms(started_at: datetime, completed_at: datetime) -> int:
        return max(0, int((completed_at - started_at).total_seconds() * 1000))
