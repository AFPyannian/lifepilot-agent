"""验证用量 API 只返回当前登录用户的数据。"""

from datetime import UTC, datetime

from app.api.server import create_app
from app.repositories.auth_repository import AuthRepository
from app.repositories.usage_repository import UsageRepository
from app.usage.models import UsageEvent
from tests.helpers import TEST_PRINCIPAL, AuthenticatedTestClient


def test_usage_api_returns_only_current_users_events(tmp_path) -> None:
    database_path = tmp_path / "usage-api.db"
    auth = AuthRepository(database_path)
    for user_id, username in (
        (TEST_PRINCIPAL.user_id, TEST_PRINCIPAL.username),
        ("other-id", "other"),
    ):
        auth.create_user(
            user_id=user_id,
            username=username,
            password_hash="test",
            role="user",
        )
    usage = UsageRepository(database_path)
    for event_id, user_id in (
        ("current-event", TEST_PRINCIPAL.user_id),
        ("other-event", "other-id"),
    ):
        usage.begin(
            UsageEvent(
                event_id=event_id,
                request_id=f"request-{event_id}",
                user_id=user_id,
                thread_id="main",
                provider="deepseek",
                model="deepseek-test",
                credential_mode="BYOK",
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                status="started",
                error_code=None,
                started_at=datetime.now(UTC),
                completed_at=None,
                duration_ms=None,
            )
        )

    app = create_app(agent_graph=object(), usage_repository=usage)
    with AuthenticatedTestClient(app) as client:
        events = client.get("/api/v1/usage/events").json()
        summary = client.get("/api/v1/usage/summary").json()

    assert [event["event_id"] for event in events] == ["current-event"]
    assert summary["requests"] == 1
