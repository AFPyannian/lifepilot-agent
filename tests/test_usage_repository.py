"""验证模型用量事件的幂等状态流转、隔离和汇总。"""

from datetime import UTC, datetime, timedelta

from langchain_core.messages import AIMessage

from app.repositories.auth_repository import AuthRepository
from app.repositories.usage_repository import UsageRepository
from app.usage.models import ModelInvocationContext, UsageEvent
from app.usage.service import UsageTracker


def _event(event_id: str, user_id: str, request_id: str = "request-1") -> UsageEvent:
    return UsageEvent(
        event_id=event_id,
        request_id=request_id,
        user_id=user_id,
        thread_id="main",
        provider="deepseek",
        model="deepseek-test",
        credential_mode="PLATFORM",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        status="started",
        error_code=None,
        started_at=datetime.now(UTC),
        completed_at=None,
        duration_ms=None,
    )


def test_usage_events_are_idempotent_and_user_scoped(tmp_path) -> None:
    database_path = tmp_path / "usage.db"
    auth = AuthRepository(database_path)
    for user_id in ("alice-id", "bob-id"):
        auth.create_user(
            user_id=user_id,
            username=user_id,
            password_hash="test",
            role="user",
        )
    repository = UsageRepository(database_path)
    event = _event("event-1", "alice-id")
    assert repository.begin(event)
    assert not repository.begin(event)
    assert repository.mark_succeeded(
        event_id=event.event_id,
        input_tokens=4,
        output_tokens=6,
        total_tokens=10,
        completed_at=datetime.now(UTC),
        duration_ms=12,
    )
    assert not repository.mark_failed(
        event_id=event.event_id,
        error_code="provider_error",
        completed_at=datetime.now(UTC),
        duration_ms=13,
    )

    alice_events = repository.list_for_user(user_id="alice-id")
    assert len(alice_events) == 1
    assert repository.list_for_user(user_id="bob-id") == []
    summary = repository.summarize(
        user_id="alice-id",
        since=datetime.now(UTC) - timedelta(minutes=1),
        until=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert summary.requests == 1
    assert summary.successful_calls == 1
    assert summary.total_tokens == 10
    assert summary.platform_calls == 1


def test_usage_tracker_extracts_langchain_token_metadata(tmp_path) -> None:
    database_path = tmp_path / "tracker.db"
    auth = AuthRepository(database_path)
    auth.create_user(
        user_id="owner-id",
        username="owner",
        password_hash="test",
        role="user",
    )
    repository = UsageRepository(database_path)
    tracker = UsageTracker(repository)
    event = tracker.start(
        context=ModelInvocationContext(
            user_id="owner-id",
            request_id="request-id",
            thread_id="thread-id",
            model_mode="BYOK",
        ),
        model="deepseek-test",
    )
    response = AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": 7,
            "output_tokens": 3,
            "total_tokens": 10,
        },
    )
    assert tracker.succeed(event, response)

    stored = repository.list_for_user(user_id="owner-id")[0]
    assert stored.status == "succeeded"
    assert stored.total_tokens == 10
