"""验证 DeepSeek 模型工厂的稳定性配置。"""

from types import SimpleNamespace
from typing import Any

from pydantic import SecretStr
from pytest import MonkeyPatch

import app.model as model_module


def test_create_model_uses_timeout_and_retries(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeChatDeepSeek:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        model_module,
        "ChatDeepSeek",
        FakeChatDeepSeek,
    )

    settings = SimpleNamespace(
        deepseek_api_key=SecretStr("test-key"),
        deepseek_model="test-model",
        deepseek_timeout_seconds=42.0,
        deepseek_max_retries=4,
    )

    model_module.create_model(settings)

    assert captured["model"] == "test-model"
    assert captured["timeout"] == 42.0
    assert captured["max_retries"] == 4
    assert captured["streaming"] is True
