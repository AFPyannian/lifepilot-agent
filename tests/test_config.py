"""验证应用配置解析和约束。"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_read_environment(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "DEEPSEEK_API_KEY",
        "test-secret-key",
    )
    monkeypatch.setenv(
        "DEEPSEEK_MODEL",
        "test-model",
    )
    monkeypatch.setenv(
        "LOG_LEVEL",
        "debug",
    )
    monkeypatch.setenv(
        "APP_DATABASE_PATH",
        str(tmp_path / "application.db"),
    )

    settings = Settings(_env_file=None)

    assert settings.deepseek_api_key.get_secret_value() == "test-secret-key"
    assert settings.deepseek_model == "test-model"
    assert settings.log_level == "DEBUG"

    assert settings.app_database_path == tmp_path / "application.db"


def test_api_key_is_masked():
    settings = Settings(
        _env_file=None,
        deepseek_api_key="highly-secret-value",
    )

    representation = repr(settings)

    assert "highly-secret-value" not in representation


def test_invalid_log_level_is_rejected(
    monkeypatch,
):
    monkeypatch.setenv(
        "DEEPSEEK_API_KEY",
        "test-key",
    )
    monkeypatch.setenv(
        "LOG_LEVEL",
        "verbose",
    )

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_api_authentication_can_be_disabled_without_key() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-deepseek-key",
        api_auth_enabled=False,
        lifepilot_api_key=None,
    )

    assert settings.api_auth_enabled is False
    assert settings.lifepilot_api_key is None


def test_api_authentication_requires_api_key() -> None:
    with pytest.raises(
        ValidationError,
        match="LIFEPILOT_API_KEY",
    ):
        Settings(
            _env_file=None,
            deepseek_api_key="test-deepseek-key",
            api_auth_enabled=True,
            lifepilot_api_key=None,
        )


def test_lifepilot_api_key_is_masked() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-deepseek-key",
        api_auth_enabled=True,
        lifepilot_api_key="secret-lifepilot-key",
    )

    assert "secret-lifepilot-key" not in repr(settings)
