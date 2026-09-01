"""提供管理员账号、授权、审计、用量和邀请码后台接口。"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.access.models import Capability, EntitlementSource
from app.api.audit import record_audit_event
from app.api.schemas import (
    AdminAuditEventItem,
    AdminAuditEventListResponse,
    AdminEntitlementItem,
    AdminEntitlementListResponse,
    AdminEntitlementRequest,
    AdminQuotaRequest,
    AdminQuotaResponse,
    AdminUsageSummaryResponse,
    AdminUserItem,
    AdminUserListResponse,
    AdminUserStatusRequest,
    CreateInvitationRequest,
    InvitationCreateResponse,
    InvitationItemResponse,
    InvitationListResponse,
    InvitationRevokeResponse,
)
from app.api.security import AdminUser, AuthServiceDependency

router = APIRouter(prefix="/admin")


def _state_dependency(request: Request, name: str) -> Any:
    dependency = getattr(request.app.state, name, None)
    if dependency is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="管理员后台服务不可用。",
        )
    return dependency


def _entitlement_item(record: Any) -> AdminEntitlementItem:
    return AdminEntitlementItem(
        id=record.id,
        user_id=record.user_id,
        capability=record.capability.value,
        source=record.source.value,
        status=record.status.value,
        starts_at=record.starts_at,
        expires_at=record.expires_at,
        created_by=record.created_by,
        created_at=record.created_at,
        revoked_at=record.revoked_at,
    )


def _quota_response(status_record: Any) -> AdminQuotaResponse:
    quota = status_record.quota
    return AdminQuotaResponse(
        user_id=quota.user_id,
        period_start=status_record.period_start,
        monthly_request_limit=quota.monthly_request_limit,
        monthly_token_limit=quota.monthly_token_limit,
        request_count=status_record.request_count,
        token_count=status_record.token_count,
        updated_by=quota.updated_by,
        updated_at=quota.updated_at,
    )


@router.get("/users", response_model=AdminUserListResponse, summary="查询用户列表")
def list_users(
    request: Request,
    _current_admin: AdminUser,
    limit: int = Query(default=100, ge=1, le=500),
) -> AdminUserListResponse:
    repository = _state_dependency(request, "auth_repository")
    return AdminUserListResponse(
        users=[
            AdminUserItem(
                id=user.id,
                username=user.username,
                role=user.role,
                status=user.status,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
            for user in repository.list_users(limit)
        ]
    )


@router.patch(
    "/users/{user_id}/status",
    response_model=AdminUserItem,
    summary="启用或禁用用户",
)
def update_user_status(
    user_id: str,
    payload: AdminUserStatusRequest,
    request: Request,
    current_admin: AdminUser,
) -> AdminUserItem:
    if user_id == current_admin.user_id and payload.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="不能禁用当前管理员账号。",
        )
    repository = _state_dependency(request, "auth_repository")
    if not repository.set_user_status(user_id, payload.status):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。"
        )
    user = repository.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。"
        )
    record_audit_event(
        request,
        user_id=current_admin.user_id,
        action="user.status_updated",
        resource_type="user",
        resource_id=user_id,
        outcome="success",
    )
    return AdminUserItem(
        id=user.id,
        username=user.username,
        role=user.role,
        status=user.status,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get(
    "/audit-events",
    response_model=AdminAuditEventListResponse,
    summary="查询审计事件",
)
def list_audit_events(
    request: Request,
    _current_admin: AdminUser,
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str | None = None,
) -> AdminAuditEventListResponse:
    repository = _state_dependency(request, "audit_repository")
    return AdminAuditEventListResponse(
        events=[
            AdminAuditEventItem(**event.__dict__)
            for event in repository.list_recent(limit=limit, user_id=user_id)
        ]
    )


@router.get(
    "/usage/summary",
    response_model=AdminUsageSummaryResponse,
    summary="查询全局模型用量",
)
def get_admin_usage_summary(
    request: Request,
    _current_admin: AdminUser,
    days: int = Query(default=30, ge=1, le=365),
) -> AdminUsageSummaryResponse:
    until = datetime.now(UTC)
    since = until - timedelta(days=days)
    summary = _state_dependency(request, "usage_repository").summarize_all(
        since=since, until=until
    )
    return AdminUsageSummaryResponse(since=since, until=until, **summary)


@router.get(
    "/users/{user_id}/quota",
    response_model=AdminQuotaResponse,
    summary="查询用户月度模型配额",
)
def get_user_quota(
    user_id: str, request: Request, _current_admin: AdminUser
) -> AdminQuotaResponse:
    auth_repository = _state_dependency(request, "auth_repository")
    if auth_repository.get_user_by_id(user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。"
        )
    service = _state_dependency(request, "quota_service")
    return _quota_response(service.get_status(user_id))


@router.put(
    "/users/{user_id}/quota",
    response_model=AdminQuotaResponse,
    summary="设置用户月度模型配额",
)
def set_user_quota(
    user_id: str,
    payload: AdminQuotaRequest,
    request: Request,
    current_admin: AdminUser,
) -> AdminQuotaResponse:
    auth_repository = _state_dependency(request, "auth_repository")
    if auth_repository.get_user_by_id(user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。"
        )
    service = _state_dependency(request, "quota_service")
    service.set_quota(
        user_id=user_id,
        monthly_request_limit=payload.monthly_request_limit,
        monthly_token_limit=payload.monthly_token_limit,
        updated_by=current_admin.user_id,
    )
    record_audit_event(
        request,
        user_id=current_admin.user_id,
        action="quota.updated",
        resource_type="user_quota",
        resource_id=user_id,
        outcome="success",
    )
    return _quota_response(service.get_status(user_id))


@router.get(
    "/users/{user_id}/entitlements",
    response_model=AdminEntitlementListResponse,
    summary="查询用户能力授权",
)
def list_user_entitlements(
    user_id: str, request: Request, _current_admin: AdminUser
) -> AdminEntitlementListResponse:
    repository = _state_dependency(request, "entitlement_repository")
    return AdminEntitlementListResponse(
        entitlements=[
            _entitlement_item(record) for record in repository.list_for_user(user_id)
        ]
    )


@router.post(
    "/users/{user_id}/entitlements",
    response_model=AdminEntitlementItem,
    status_code=status.HTTP_201_CREATED,
    summary="授予用户能力",
)
def grant_user_entitlement(
    user_id: str,
    payload: AdminEntitlementRequest,
    request: Request,
    current_admin: AdminUser,
) -> AdminEntitlementItem:
    auth_repository = _state_dependency(request, "auth_repository")
    if auth_repository.get_user_by_id(user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。"
        )
    record = _state_dependency(request, "entitlement_repository").grant(
        user_id=user_id,
        capability=Capability(payload.capability),
        source=EntitlementSource.ADMIN,
        created_by=current_admin.user_id,
        expires_at=payload.expires_at,
    )
    record_audit_event(
        request,
        user_id=current_admin.user_id,
        action="entitlement.granted",
        resource_type="entitlement",
        resource_id=record.id,
        outcome="success",
    )
    return _entitlement_item(record)


@router.delete(
    "/entitlements/{entitlement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="撤销用户能力",
)
def revoke_user_entitlement(
    entitlement_id: str, request: Request, current_admin: AdminUser
) -> None:
    if not _state_dependency(request, "entitlement_repository").revoke(entitlement_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="授权不存在或已经撤销。",
        )
    record_audit_event(
        request,
        user_id=current_admin.user_id,
        action="entitlement.revoked",
        resource_type="entitlement",
        resource_id=entitlement_id,
        outcome="success",
    )


@router.post(
    "/invitations",
    response_model=InvitationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建注册邀请码",
)
def create_invitation(
    payload: CreateInvitationRequest,
    request: Request,
    current_admin: AdminUser,
    auth_service: AuthServiceDependency,
) -> InvitationCreateResponse:
    """创建一次性注册邀请码。"""
    settings = request.app.state.settings
    try:
        grant = auth_service.create_invitation(
            created_by=current_admin.user_id,
            expires_in_hours=payload.expires_in_hours,
            maximum_ttl_hours=settings.auth_invitation_max_ttl_hours,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    record_audit_event(
        request,
        user_id=current_admin.user_id,
        action="invite.created",
        resource_type="registration_invite",
        resource_id=grant.invitation.id,
        outcome="success",
    )
    return InvitationCreateResponse(
        id=grant.invitation.id,
        invite_code=grant.invite_code,
        expires_at=grant.invitation.expires_at,
    )


@router.get(
    "/invitations",
    response_model=InvitationListResponse,
    summary="查询注册邀请码",
)
def list_invitations(
    _current_admin: AdminUser,
    auth_service: AuthServiceDependency,
) -> InvitationListResponse:
    """返回不包含邀请码原文和摘要的管理列表。"""
    return InvitationListResponse(
        invitations=[
            InvitationItemResponse(
                id=item.id,
                created_by_username=item.created_by_username,
                expires_at=item.expires_at,
                used_by_username=item.used_by_username,
                used_at=item.used_at,
                revoked_at=item.revoked_at,
                created_at=item.created_at,
            )
            for item in auth_service.list_invitations()
        ]
    )


@router.delete(
    "/invitations/{invitation_id}",
    response_model=InvitationRevokeResponse,
    summary="撤销注册邀请码",
)
def revoke_invitation(
    invitation_id: str,
    request: Request,
    current_admin: AdminUser,
    auth_service: AuthServiceDependency,
) -> InvitationRevokeResponse:
    """撤销未使用的邀请码。"""
    revoked = auth_service.revoke_invitation(invitation_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邀请码不存在、已经使用或已经撤销。",
        )
    record_audit_event(
        request,
        user_id=current_admin.user_id,
        action="invite.revoked",
        resource_type="registration_invite",
        resource_id=invitation_id,
        outcome="success",
    )
    return InvitationRevokeResponse(
        id=invitation_id,
        revoked=True,
    )
