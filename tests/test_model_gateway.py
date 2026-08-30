"""验证模型网关按用户路由凭据并隔离认证故障。"""

from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import SecretStr

import app.model_gateway as gateway_module
from app.credentials.models import ResolvedCredential
from app.exceptions import ModelServiceError
from app.model_gateway import DeepSeekModelGateway
from app.usage.models import ModelInvocationContext, UsageEvent


class FakeAccessPolicy:
    def __init__(self) -> None:
        self.authorized: list[tuple[str, str]] = []

    def authorize(self, *, user_id, capability) -> None:
        self.authorized.append((user_id, capability.value))


class FakeUsageTracker:
    def __init__(self) -> None:
        self.started: list[ModelInvocationContext] = []
        self.succeeded: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def start(self, *, context, model) -> UsageEvent:
        self.started.append(context)
        return UsageEvent(
            event_id=f"event-{len(self.started)}",
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

    def succeed(self, event, response) -> bool:
        del response
        self.succeeded.append(event.event_id)
        return True

    def fail(self, event, error_code) -> bool:
        self.failed.append((event.event_id, error_code))
        return True


class FakeCredentialService:
    """记录模型网关解析、使用和禁用的凭据。"""

    def __init__(self) -> None:
        self.secrets = {
            "alice": ResolvedCredential("alice-credential", SecretStr("alice-key")),
            "bob": ResolvedCredential("bob-credential", SecretStr("bob-key")),
        }
        self.used: list[str] = []
        self.invalid: list[str] = []

    def resolve_active(self, *, user_id: str) -> ResolvedCredential:
        return self.secrets[user_id]

    def mark_used(self, credential_id: str) -> None:
        self.used.append(credential_id)

    def mark_invalid(self, credential_id: str) -> None:
        self.invalid.append(credential_id)


class FakeModel:
    def __init__(self, *, fail_status: int | None = None) -> None:
        self.fail_status = fail_status

    def bind_tools(self, tools) -> "FakeModel":
        del tools
        return self

    def invoke(self, messages):
        del messages

        if self.fail_status is not None:
            error = RuntimeError("sanitized test failure")
            error.status_code = self.fail_status  # type: ignore[attr-defined]
            raise error

        return AIMessage(content="ok")


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        byok_enabled=True,
        platform_model_enabled=True,
        deepseek_api_key=SecretStr("platform-key"),
        deepseek_model="deepseek-test",
    )


def test_gateway_uses_each_users_own_key(monkeypatch) -> None:
    credential_service = FakeCredentialService()
    captured_keys: list[str] = []

    def fake_create_model(_settings, *, api_key, **kwargs: Any):
        del kwargs
        captured_keys.append(api_key.get_secret_value())
        return FakeModel()

    monkeypatch.setattr(gateway_module, "create_model", fake_create_model)
    access_policy = FakeAccessPolicy()
    usage_tracker = FakeUsageTracker()
    gateway = DeepSeekModelGateway(
        settings=settings(),
        credential_service=credential_service,  # type: ignore[arg-type]
        access_policy=access_policy,  # type: ignore[arg-type]
        usage_tracker=usage_tracker,  # type: ignore[arg-type]
    )

    for user_id in ("alice", "bob"):
        gateway.invoke(
            context=ModelInvocationContext(
                user_id=user_id,
                request_id=f"request-{user_id}",
                thread_id="main",
                model_mode="BYOK",
            ),
            tools=[],
            messages=[HumanMessage(content="hello")],
        )

    assert captured_keys == ["alice-key", "bob-key"]
    assert credential_service.used == ["alice-credential", "bob-credential"]
    assert access_policy.authorized == [
        ("alice", "model.byok"),
        ("bob", "model.byok"),
    ]
    assert usage_tracker.succeeded == ["event-1", "event-2"]


def test_gateway_invalidates_only_the_failing_users_key(monkeypatch) -> None:
    credential_service = FakeCredentialService()
    monkeypatch.setattr(
        gateway_module,
        "create_model",
        lambda *_args, **_kwargs: FakeModel(fail_status=401),
    )
    usage_tracker = FakeUsageTracker()
    gateway = DeepSeekModelGateway(
        settings=settings(),
        credential_service=credential_service,  # type: ignore[arg-type]
        access_policy=FakeAccessPolicy(),  # type: ignore[arg-type]
        usage_tracker=usage_tracker,  # type: ignore[arg-type]
    )

    with suppress(ModelServiceError):
        gateway.invoke(
            context=ModelInvocationContext(
                user_id="alice",
                request_id="request-alice",
                thread_id="main",
                model_mode="BYOK",
            ),
            tools=[],
            messages=[HumanMessage(content="hello")],
        )

    assert credential_service.invalid == ["alice-credential"]
    assert "bob-credential" not in credential_service.invalid
    assert usage_tracker.failed == [("event-1", "provider_auth")]
