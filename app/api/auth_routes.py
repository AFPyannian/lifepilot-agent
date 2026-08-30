"""提供账号登录和 Session 生命周期接口。"""

from fastapi import APIRouter, HTTPException, Request, status

from app.api.audit import record_audit_event
from app.api.schemas import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RegisterRequest,
    RegistrationStatusResponse,
)
from app.api.security import AuthServiceDependency, CurrentUser
from app.auth.errors import (
    RegistrationClosedError,
    RegistrationDeniedError,
    UsernameUnavailableError,
)
from app.auth.models import SessionGrant
from app.auth.rate_limit import LoginRateLimiter
from app.auth.service import InvalidCredentialsError

router = APIRouter(prefix="/auth")


def _get_login_limiter(request: Request) -> LoginRateLimiter:
    limiter = getattr(request.app.state, "login_rate_limiter", None)
    if limiter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="登录保护服务不可用。",
        )
    return limiter


def _get_registration_limiter(request: Request) -> LoginRateLimiter:
    limiter = getattr(request.app.state, "registration_rate_limiter", None)
    if limiter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="注册保护服务不可用。",
        )
    return limiter


def _grant_response(grant: SessionGrant) -> LoginResponse:
    """将认证服务签发结果转换成公开响应。"""
    return LoginResponse(
        access_token=grant.access_token,
        expires_at=grant.expires_at,
        user=CurrentUserResponse(
            id=grant.principal.user_id,
            username=grant.principal.username,
            role=grant.principal.role,
            status=grant.principal.status,
        ),
    )


@router.post("/login", response_model=LoginResponse, summary="账号密码登录")
def login(
    payload: LoginRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> LoginResponse:
    """验证账号密码并签发可撤销 Session。"""
    limiter = _get_login_limiter(request)
    client_host = request.client.host if request.client is not None else "unknown"
    limit_key = limiter.build_key(client_host, payload.username)
    retry_after = limiter.retry_after(limit_key)

    if retry_after is not None:
        record_audit_event(
            request,
            user_id=None,
            action="auth.login",
            resource_type="session",
            resource_id=None,
            outcome="rate_limited",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录失败次数过多，请稍后重试。",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        grant = auth_service.login(payload.username, payload.password)
    except InvalidCredentialsError as error:
        limiter.record_failure(limit_key)
        record_audit_event(
            request,
            user_id=None,
            action="auth.login",
            resource_type="session",
            resource_id=None,
            outcome="denied",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    limiter.reset(limit_key)
    record_audit_event(
        request,
        user_id=grant.principal.user_id,
        action="auth.login",
        resource_type="session",
        resource_id=grant.principal.session_id,
        outcome="success",
    )
    return _grant_response(grant)


@router.get(
    "/registration",
    response_model=RegistrationStatusResponse,
    summary="读取注册状态",
)
def get_registration_status(
    auth_service: AuthServiceDependency,
) -> RegistrationStatusResponse:
    """返回当前实例的注册策略。"""
    mode = auth_service.registration_mode
    return RegistrationStatusResponse(
        mode=mode,
        enabled=mode == "invite",
    )


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="使用邀请码注册",
)
def register(
    payload: RegisterRequest,
    request: Request,
    auth_service: AuthServiceDependency,
) -> LoginResponse:
    """使用一次性邀请码注册普通用户。"""
    if auth_service.registration_mode != "invite":
        record_audit_event(
            request,
            user_id=None,
            action="auth.register",
            resource_type="user",
            resource_id=None,
            outcome="closed",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前实例没有开放注册。",
        )

    limiter = _get_registration_limiter(request)
    client_host = request.client.host if request.client is not None else "unknown"
    limit_key = limiter.build_registration_key(
        client_host,
        payload.username,
        payload.invite_code,
    )
    retry_after = limiter.retry_after(limit_key)
    if retry_after is not None:
        record_audit_event(
            request,
            user_id=None,
            action="auth.register",
            resource_type="user",
            resource_id=None,
            outcome="rate_limited",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="注册尝试次数过多，请稍后重试。",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        grant = auth_service.register(
            username=payload.username,
            password=payload.password,
            invite_code=payload.invite_code,
        )
    except RegistrationClosedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前实例没有开放注册。",
        ) from error
    except (
        RegistrationDeniedError,
        UsernameUnavailableError,
        ValueError,
    ) as error:
        limiter.record_failure(limit_key)
        record_audit_event(
            request,
            user_id=None,
            action="auth.register",
            resource_type="user",
            resource_id=None,
            outcome="denied",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无法完成注册，请检查用户名、密码和邀请码。",
        ) from error

    limiter.reset(limit_key)
    record_audit_event(
        request,
        user_id=grant.principal.user_id,
        action="auth.register",
        resource_type="user",
        resource_id=grant.principal.user_id,
        outcome="success",
    )
    return _grant_response(grant)


@router.get("/me", response_model=CurrentUserResponse, summary="读取当前登录用户")
def get_current_user(current_user: CurrentUser) -> CurrentUserResponse:
    """返回当前 Session 对应的公开账号信息。"""
    return CurrentUserResponse(
        id=current_user.user_id,
        username=current_user.username,
        role=current_user.role,
        status=current_user.status,
    )


@router.post("/logout", response_model=LogoutResponse, summary="退出当前设备")
def logout(
    request: Request,
    current_user: CurrentUser,
    auth_service: AuthServiceDependency,
) -> LogoutResponse:
    """撤销当前请求使用的 Session。"""
    revoked = auth_service.logout(current_user)
    record_audit_event(
        request,
        user_id=current_user.user_id,
        action="auth.logout",
        resource_type="session",
        resource_id=current_user.session_id,
        outcome="success",
    )
    return LogoutResponse(revoked=revoked)


@router.post("/logout-all", response_model=LogoutResponse, summary="退出全部设备")
def logout_all(
    request: Request,
    current_user: CurrentUser,
    auth_service: AuthServiceDependency,
) -> LogoutResponse:
    """撤销当前用户的全部有效 Session。"""
    revoked_count = auth_service.logout_all(current_user)
    record_audit_event(
        request,
        user_id=current_user.user_id,
        action="auth.logout_all",
        resource_type="user",
        resource_id=current_user.user_id,
        outcome="success",
    )
    return LogoutResponse(revoked=revoked_count > 0)


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="修改当前账号密码",
)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: CurrentUser,
    auth_service: AuthServiceDependency,
) -> None:
    """更新密码并撤销包括当前设备在内的全部 Session。"""
    try:
        auth_service.change_password(
            principal=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except (InvalidCredentialsError, ValueError) as error:
        record_audit_event(
            request,
            user_id=current_user.user_id,
            action="auth.change_password",
            resource_type="user",
            resource_id=current_user.user_id,
            outcome="denied",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    record_audit_event(
        request,
        user_id=current_user.user_id,
        action="auth.change_password",
        resource_type="user",
        resource_id=current_user.user_id,
        outcome="success",
    )
