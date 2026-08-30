"""提供当前登录用户自己的模型用量查询。"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.schemas import UsageEventResponse, UsageSummaryResponse
from app.api.security import CurrentUser
from app.repositories.usage_repository import UsageRepository

router = APIRouter()


def _get_repository(request: Request) -> UsageRepository:
    repository = getattr(request.app.state, "usage_repository", None)
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="用量服务不可用。",
        )
    return repository


@router.get("/usage/summary", response_model=UsageSummaryResponse)
def get_usage_summary(
    request: Request,
    current_user: CurrentUser,
    since: datetime | None = None,
    until: datetime | None = None,
) -> UsageSummaryResponse:
    """返回当前月或显式 UTC 时间范围内的用量汇总。"""
    now = datetime.now(UTC)
    effective_since = since or now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    effective_until = until or now
    if effective_since.tzinfo is None or effective_until.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="since 和 until 必须包含时区。",
        )
    if effective_since >= effective_until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="since 必须早于 until。",
        )
    summary = _get_repository(request).summarize(
        user_id=current_user.user_id,
        since=effective_since,
        until=effective_until,
    )
    return UsageSummaryResponse(**summary.__dict__)


@router.get("/usage/events", response_model=list[UsageEventResponse])
def list_usage_events(
    request: Request,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=100),
    before: datetime | None = None,
) -> list[UsageEventResponse]:
    """按时间倒序返回当前用户自己的模型调用事件。"""
    events = _get_repository(request).list_for_user(
        user_id=current_user.user_id,
        limit=limit,
        before=before,
    )
    return [
        UsageEventResponse(
            event_id=event.event_id,
            request_id=event.request_id,
            thread_id=event.thread_id,
            provider="deepseek",
            model=event.model,
            credential_mode=event.credential_mode,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            total_tokens=event.total_tokens,
            status=event.status,
            error_code=event.error_code,
            started_at=event.started_at,
            completed_at=event.completed_at,
            duration_ms=event.duration_ms,
        )
        for event in events
    ]
