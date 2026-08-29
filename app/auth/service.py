"""实现登录、Session 签发和认证。"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.auth.models import Principal, SessionGrant
from app.auth.passwords import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.repositories.auth_repository import AuthRepository


class InvalidCredentialsError(RuntimeError):
    """表示用户名、密码或账号状态不允许登录。"""


class AuthService:
    """提供账号密码认证和 Session 生命周期管理。"""

    def __init__(
        self,
        repository: AuthRepository,
        session_ttl_hours: int = 168,
        touch_interval_seconds: int = 300,
    ) -> None:
        self._repository = repository
        self._session_ttl = timedelta(hours=session_ttl_hours)
        self._touch_interval = timedelta(seconds=touch_interval_seconds)

    @staticmethod
    def hash_session_token(token: str) -> str:
        """生成用于数据库查询的 Session Token 摘要。"""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def login(
        self,
        username: str,
        password: str,
    ) -> SessionGrant:
        """验证账号密码并签发新的不透明 Session Token。"""
        user = self._repository.get_user_by_username(username)
        password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
        password_matches = verify_password(password_hash, password)

        if user is None or not password_matches or user.status != "active":
            raise InvalidCredentialsError("用户名或密码错误。")

        if password_needs_rehash(user.password_hash):
            self._repository.update_password_hash(
                user.id,
                hash_password(password),
            )

        now = datetime.now(UTC)
        expires_at = now + self._session_ttl
        session_id = str(uuid4())
        access_token = secrets.token_urlsafe(48)

        self._repository.create_session(
            session_id=session_id,
            user_id=user.id,
            token_hash=self.hash_session_token(access_token),
            expires_at=expires_at,
        )

        return SessionGrant(
            access_token=access_token,
            expires_at=expires_at,
            principal=Principal(
                user_id=user.id,
                username=user.username,
                role=user.role,
                status=user.status,
                session_id=session_id,
            ),
        )

    def authenticate(self, access_token: str) -> Principal | None:
        """验证 Session Token 并返回服务端可信身份。"""
        clean_token = access_token.strip()
        if not clean_token:
            return None

        now = datetime.now(UTC)
        principal = self._repository.find_principal_by_token_hash(
            self.hash_session_token(clean_token),
            now,
        )

        if principal is None:
            return None

        self._repository.touch_session(
            principal.session_id,
            now,
            now - self._touch_interval,
        )
        return principal

    def change_password(
        self,
        principal: Principal,
        current_password: str,
        new_password: str,
    ) -> None:
        """验证当前密码、更新哈希并撤销全部 Session。"""
        user = self._repository.get_user_by_id(principal.user_id)
        if user is None or not verify_password(user.password_hash, current_password):
            raise InvalidCredentialsError("当前密码错误。")

        self._repository.update_password_hash(
            principal.user_id,
            hash_password(new_password),
        )
        self._repository.revoke_all_sessions(principal.user_id)

    def logout(self, principal: Principal) -> bool:
        """撤销当前 Session。"""
        return self._repository.revoke_session(principal.session_id)

    def logout_all(self, principal: Principal) -> int:
        """撤销当前用户的全部 Session。"""
        return self._repository.revoke_all_sessions(principal.user_id)
