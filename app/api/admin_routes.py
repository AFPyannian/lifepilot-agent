"""提供管理员邀请码管理接口。"""

from fastapi import APIRouter, HTTPException, Request, status

from app.api.audit import record_audit_event
from app.api.schemas import (
    CreateInvitationRequest,
    InvitationCreateResponse,
    InvitationItemResponse,
    InvitationListResponse,
    InvitationRevokeResponse,
)
from app.api.security import AdminUser, AuthServiceDependency

router = APIRouter(prefix="/admin")


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
