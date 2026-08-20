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
        "TODO_DATABASE_PATH",
        str(tmp_path / "todos.db"),
    )

    settings = Settings(_env_file=None)

    assert (
        settings.deepseek_api_key.get_secret_value()
        == "test-secret-key"
    )
    assert settings.deepseek_model == "test-model"
    assert settings.log_level == "DEBUG"

    assert (
        settings.todo_database_path
        == tmp_path / "todos.db"
    )


def test_api_key_is_masked():
    settings = Settings(
        _env_file=None,
        deepseek_api_key="highly-secret-value",
    )

    representation = repr(settings)

    assert (
        "highly-secret-value"
        not in representation
    )


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