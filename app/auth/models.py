"""定义认证和用户身份数据模型。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

UserRole = Literal["admin", "user"]
UserStatus = Literal["active", "disabled"]
RegistrationMode = Literal["closed", "invite"]


@dataclass(frozen=True)
class UserRecord:
    """表示数据库中的完整用户记录。"""

    id: str
    username: str
    username_normalized: str
    password_hash: str
    role: UserRole
    status: UserStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Principal:
    """表示已经通过服务端认证的当前用户。"""

    user_id: str
    username: str
    role: UserRole
    status: UserStatus
    session_id: str


@dataclass(frozen=True)
class SessionGrant:
    """表示登录成功后签发给客户端的 Session。"""

    access_token: str
    expires_at: datetime
    principal: Principal


@dataclass(frozen=True)
class InvitationRecord:
    """表示管理员创建的一次性注册邀请。"""

    id: str
    created_by: str
    created_by_username: str
    expires_at: datetime
    used_by: str | None
    used_by_username: str | None
    used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class InvitationGrant:
    """表示只向管理员展示一次的邀请码原文。"""

    invite_code: str
    invitation: InvitationRecord
