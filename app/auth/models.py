"""定义认证和用户身份数据模型。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

UserRole = Literal["admin", "user"]
UserStatus = Literal["active", "disabled"]


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
