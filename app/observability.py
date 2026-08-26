"""根据应用配置启用或关闭 LangSmith 追踪。"""


import logging
import os

from app.config import Settings


logger = logging.getLogger(
    "lifepilot.observability"
)


def configure_observability(
    settings: Settings,
) -> None:
    """将 LangSmith 配置同步到当前进程环境。"""

    os.environ["LANGSMITH_TRACING"] = (
        "true"
        if settings.langsmith_tracing
        else "false"
    )

    os.environ[
        "LANGSMITH_HIDE_INPUTS"
    ] = (
        "true"
        if settings.langsmith_hide_inputs
        else "false"
    )

    os.environ[
        "LANGSMITH_HIDE_OUTPUTS"
    ] = (
        "true"
        if settings.langsmith_hide_outputs
        else "false"
    )

    if not settings.langsmith_tracing:
        logger.info(
            "LangSmith tracing is disabled"
        )
        return

    if settings.langsmith_api_key is None:
        raise ValueError(
            "LangSmith tracing enabled "
            "without API key"
        )

    api_key = (
        settings.langsmith_api_key
        .get_secret_value()
        .strip()
    )

    if not api_key:
        raise ValueError(
            "LangSmith API key is empty"
        )

    os.environ["LANGSMITH_API_KEY"] = (
        api_key
    )

    os.environ["LANGSMITH_PROJECT"] = (
        settings.langsmith_project
    )

    os.environ["LANGSMITH_ENDPOINT"] = (
        settings.langsmith_endpoint
    )

    workspace_id = (
        settings.langsmith_workspace_id
        or ""
    ).strip()

    if workspace_id:
        os.environ[
            "LANGSMITH_WORKSPACE_ID"
        ] = workspace_id
    else:
        os.environ.pop(
            "LANGSMITH_WORKSPACE_ID",
            None,
        )

    logger.info(
        "LangSmith tracing enabled project=%s environment=%s hide_inputs=%s hide_outputs=%s",
        settings.langsmith_project,
        settings.app_environment,
        settings.langsmith_hide_inputs,
        settings.langsmith_hide_outputs,
    )