"""提供基于不透明 Session Token 的用户认证。"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import Principal
from app.auth.service import AuthService

bearer_scheme = HTTPBearer(
    scheme_name="LifePilotSession",
    description="登录接口签发的不透明 Session Token",
    auto_error=False,
)


def get_auth_service(request: Request) -> AuthService:
    """从应用状态读取认证服务。"""
    auth_service: AuthService | None = getattr(
        request.app.state,
        "auth_service",
        None,
    )
    if auth_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证服务不可用。",
        )
    return auth_service


AuthServiceDependency = Annotated[
    AuthService,
    Depends(get_auth_service),
]


def require_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    auth_service: AuthServiceDependency,
) -> Principal:
    """验证 Session，并返回服务端可信用户身份。"""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = auth_service.authenticate(credentials.credentials)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态无效或已经过期。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


CurrentUser = Annotated[
    Principal,
    Depends(require_current_user),
]


def require_admin(current_user: CurrentUser) -> Principal:
    """只允许管理员访问。"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限。",
        )
    return current_user


AdminUser = Annotated[
    Principal,
    Depends(require_admin),
]
