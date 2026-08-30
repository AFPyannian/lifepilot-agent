"""验证模型网关按用户路由凭据并隔离认证故障。"""

from contextlib import suppress
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import SecretStr

import app.model_gateway as gateway_module
from app.credentials.models import ResolvedCredential
from app.exceptions import ModelServiceError
from app.model_gateway import DeepSeekModelGateway


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
    )


def test_gateway_uses_each_users_own_key(monkeypatch) -> None:
    credential_service = FakeCredentialService()
    captured_keys: list[str] = []

    def fake_create_model(_settings, *, api_key, **kwargs: Any):
        del kwargs
        captured_keys.append(api_key.get_secret_value())
        return FakeModel()

    monkeypatch.setattr(gateway_module, "create_model", fake_create_model)
    gateway = DeepSeekModelGateway(
        settings=settings(),
        credential_service=credential_service,  # type: ignore[arg-type]
    )

    for user_id in ("alice", "bob"):
        gateway.invoke(
            user_id=user_id,
            model_mode="BYOK",
            tools=[],
            messages=[HumanMessage(content="hello")],
        )

    assert captured_keys == ["alice-key", "bob-key"]
    assert credential_service.used == ["alice-credential", "bob-credential"]


def test_gateway_invalidates_only_the_failing_users_key(monkeypatch) -> None:
    credential_service = FakeCredentialService()
    monkeypatch.setattr(
        gateway_module,
        "create_model",
        lambda *_args, **_kwargs: FakeModel(fail_status=401),
    )
    gateway = DeepSeekModelGateway(
        settings=settings(),
        credential_service=credential_service,  # type: ignore[arg-type]
    )

    with suppress(ModelServiceError):
        gateway.invoke(
            user_id="alice",
            model_mode="BYOK",
            tools=[],
            messages=[HumanMessage(content="hello")],
        )

    assert credential_service.invalid == ["alice-credential"]
    assert "bob-credential" not in credential_service.invalid
