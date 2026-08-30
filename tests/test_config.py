"""验证应用配置解析和约束。"""

import base64
import json

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


def test_auth_session_defaults_are_safe() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-deepseek-key",
    )

    assert settings.auth_session_ttl_hours == 168
    assert settings.auth_session_touch_interval_seconds == 300
    assert settings.auth_login_max_failures == 5
    assert settings.registration_mode == "closed"
    assert settings.auth_registration_max_failures == 10
    assert settings.auth_invitation_max_ttl_hours == 720
    assert settings.local_cli_owner_id == "local-user"


def test_auth_session_ttl_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            deepseek_api_key="test-deepseek-key",
            auth_session_ttl_hours=0,
        )


def test_login_failure_limit_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            deepseek_api_key="test-deepseek-key",
            auth_login_max_failures=0,
        )


def test_registration_mode_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            deepseek_api_key="test-deepseek-key",
            registration_mode="open",
        )


def test_unknown_legacy_api_key_settings_are_ignored() -> None:
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-deepseek-key",
        api_auth_enabled=True,
        lifepilot_api_key="secret-lifepilot-key",
    )

    assert not hasattr(settings, "lifepilot_api_key")
    assert "secret-lifepilot-key" not in repr(settings)


def test_byok_requires_a_valid_versioned_master_key() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            deepseek_api_key="test-deepseek-key",
            byok_enabled=True,
        )


def test_byok_master_keyring_is_decoded() -> None:
    encoded_key = base64.urlsafe_b64encode(b"a" * 32).decode()
    settings = Settings(
        _env_file=None,
        deepseek_api_key="test-deepseek-key",
        byok_enabled=True,
        provider_credential_master_keys=json.dumps({"v1": encoded_key}),
    )

    assert settings.provider_credential_keyring() == {"v1": b"a" * 32}
