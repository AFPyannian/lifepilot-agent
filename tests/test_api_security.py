"""验证 Session 认证、限流和安全响应头。"""

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.api.server import create_app
from tests.helpers import (
    TEST_ACCESS_TOKEN,
    FakeAuthService,
)


class FakeGraph:
    """提供安全接口测试所需的最小 Agent 图。"""

    def get_state(self, config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(next=())

    def invoke(
        self,
        input_data: dict[str, Any] | None,
        config: dict[str, Any],
        context: Any | None = None,
    ) -> dict[str, Any]:
        if input_data is None:
            return {"messages": []}
        return {
            "messages": [
                *input_data["messages"],
                AIMessage(content="测试回复"),
            ]
        }


def create_settings(request_limit: int = 60) -> SimpleNamespace:
    """创建不读取本地环境文件的最小测试配置。"""
    return SimpleNamespace(
        api_rate_limit_enabled=True,
        api_rate_limit_requests=request_limit,
        api_rate_limit_window_seconds=60,
        agent_recursion_limit=25,
        app_environment="test",
    )


def create_client(
    *,
    request_limit: int = 60,
    auth_service: Any = ...,
) -> TestClient:
    """创建启用 Session 认证和限流的测试客户端。"""
    active_auth_service = FakeAuthService() if auth_service is ... else auth_service
    application = create_app(
        agent_graph=FakeGraph(),
        settings=create_settings(request_limit),
        auth_service=active_auth_service,
    )
    return TestClient(application)


def chat_payload() -> dict[str, str]:
    return {
        "message": "你好",
        "thread_id": "security-test-thread",
    }


def bearer_headers(token: str = TEST_ACCESS_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_endpoint_is_public() -> None:
    with create_client() as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_ready_endpoint_is_public() -> None:
    with create_client() as client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 200


def test_chat_rejects_missing_session() -> None:
    with create_client() as client:
        response = client.post("/api/v1/chat", json=chat_payload())
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_chat_rejects_invalid_session() -> None:
    with create_client() as client:
        response = client.post(
            "/api/v1/chat",
            headers=bearer_headers("wrong-token"),
            json=chat_payload(),
        )
    assert response.status_code == 401


def test_shared_api_key_no_longer_authenticates() -> None:
    with create_client() as client:
        response = client.post(
            "/api/v1/chat",
            headers={"X-API-Key": "legacy-key"},
            json=chat_payload(),
        )
    assert response.status_code == 401


def test_chat_accepts_valid_session() -> None:
    with create_client() as client:
        response = client.post(
            "/api/v1/chat",
            headers=bearer_headers(),
            json=chat_payload(),
        )
    assert response.status_code == 200


def test_missing_authentication_service_returns_503() -> None:
    with create_client(auth_service=None) as client:
        response = client.post(
            "/api/v1/chat",
            headers=bearer_headers(),
            json=chat_payload(),
        )
    assert response.status_code == 503


def test_rate_limit_returns_429() -> None:
    headers = bearer_headers()
    with create_client(request_limit=2) as client:
        first = client.post("/api/v1/chat", headers=headers, json=chat_payload())
        second = client.post("/api/v1/chat", headers=headers, json=chat_payload())
        third = client.post("/api/v1/chat", headers=headers, json=chat_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert "retry-after" in third.headers
    assert "x-request-id" in third.headers


def test_security_headers_are_added() -> None:
    with create_client() as client:
        response = client.get("/api/v1/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
