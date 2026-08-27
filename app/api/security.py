"""提供 LifePilot HTTP API 密钥认证。"""

import secrets
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import SecretStr

api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="LifePilotApiKey",
    description="LifePilot API access key",
    auto_error=False,
)


def _get_secret_value(value: SecretStr | str | None) -> str:
    """读取 Pydantic 密钥或普通字符串，并清理空白。"""
    if isinstance(value, SecretStr):
        return value.get_secret_value().strip()

    if isinstance(value, str):
        return value.strip()

    return ""


async def require_api_key(
    request: Request,
    provided_api_key: Annotated[
        str | None,
        Security(api_key_header),
    ],
) -> None:
    """在应用启用认证时验证客户端提供的 API 密钥。"""
    settings = getattr(request.app.state, "settings", None)
    auth_enabled = getattr(settings, "api_auth_enabled", False)

    if not auth_enabled:
        return

    configured_api_key = _get_secret_value(getattr(settings, "lifepilot_api_key", None))

    if not configured_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured correctly",
        )

    if provided_api_key is None or not secrets.compare_digest(
        provided_api_key,
        configured_api_key,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
