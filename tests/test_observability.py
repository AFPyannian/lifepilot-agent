import os

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.observability import (
    configure_observability,
)


def test_tracing_disabled(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "LANGSMITH_TRACING",
        raising=False,
    )

    settings = Settings(
        deepseek_api_key="test-key",
        langsmith_tracing=False,
    )

    configure_observability(
        settings
    )

    assert (
        os.environ["LANGSMITH_TRACING"]
        == "false"
    )


def test_tracing_exports_environment(
    monkeypatch,
) -> None:
    monkeypatch.delenv(
        "LANGSMITH_API_KEY",
        raising=False,
    )

    settings = Settings(
        deepseek_api_key="test-key",
        langsmith_tracing=True,
        langsmith_api_key=(
            "langsmith-test-key"
        ),
        langsmith_project=(
            "lifepilot-test"
        ),
        app_environment="test",
    )

    configure_observability(
        settings
    )

    assert (
        os.environ["LANGSMITH_TRACING"]
        == "true"
    )

    assert (
        os.environ["LANGSMITH_PROJECT"]
        == "lifepilot-test"
    )

    assert (
        os.environ["LANGSMITH_API_KEY"]
        == "langsmith-test-key"
    )


def test_tracing_requires_api_key(
) -> None:
    with pytest.raises(
        ValidationError
    ):
        Settings(
            deepseek_api_key="test-key",
            langsmith_tracing=True,
            langsmith_api_key="",
        )