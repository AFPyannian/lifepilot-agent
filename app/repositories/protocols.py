"""定义本地与生产仓储共同遵循的结构化契约。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.access.models import Capability, EntitlementRecord, EntitlementSource
    from app.auth.models import InvitationRecord, Principal, UserRecord
    from app.credentials.models import ProviderCredentialRecord
    from app.domain.models import (
        AuditEvent,
        Conversation,
        NoteItem,
        TodoItem,
        UserMemory,
        UserProfile,
    )
    from app.quota.models import QuotaStatus, UserQuota
    from app.usage.models import UsageEvent, UsageSummary


@runtime_checkable
class AuditRepositoryProtocol(Protocol):
    """审计事件持久化契约。"""

    def record(
        self,
        *,
        request_id: str,
        user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
    ) -> None: ...

    def list_recent(
        self, *, limit: int = 100, user_id: str | None = None
    ) -> list[AuditEvent]: ...


@runtime_checkable
class AuthRepositoryProtocol(Protocol):
    """账号、Session 和邀请持久化契约。"""

    def create_user(
        self, *, user_id: str, username: str, password_hash: str, role: str
    ) -> UserRecord: ...

    def get_user_by_username(self, username: str) -> UserRecord | None: ...
    def get_user_by_id(self, user_id: str) -> UserRecord | None: ...
    def list_users(self, limit: int = 100) -> list[UserRecord]: ...
    def update_password_hash(self, user_id: str, password_hash: str) -> bool: ...
    def set_user_status(self, user_id: str, status: str) -> bool: ...

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None: ...

    def find_principal_by_token_hash(
        self, token_hash: str, now: datetime
    ) -> Principal | None: ...

    def touch_session(
        self, session_id: str, now: datetime, minimum_last_seen: datetime
    ) -> None: ...

    def revoke_session(self, session_id: str) -> bool: ...
    def revoke_all_sessions(self, user_id: str) -> int: ...
    def delete_expired_sessions(self, now: datetime) -> int: ...

    def create_invitation(
        self,
        *,
        invitation_id: str,
        code_hash: str,
        created_by: str,
        expires_at: datetime,
    ) -> InvitationRecord: ...

    def get_invitation(self, invitation_id: str) -> InvitationRecord | None: ...
    def list_invitations(self) -> list[InvitationRecord]: ...
    def revoke_invitation(self, invitation_id: str) -> bool: ...

    def register_with_invitation(
        self,
        *,
        user_id: str,
        username: str,
        password_hash: str,
        invitation_code_hash: str,
        now: datetime,
    ) -> UserRecord: ...


@runtime_checkable
class ConversationRepositoryProtocol(Protocol):
    """会话元数据持久化契约。"""

    def record_message(
        self, owner_id: str, thread_id: str, first_message: str
    ) -> None: ...

    def touch(self, owner_id: str, thread_id: str) -> bool: ...
    def list_conversations(
        self, owner_id: str, limit: int = 50
    ) -> list[Conversation]: ...

    def get(self, owner_id: str, thread_id: str) -> Conversation | None: ...
    def rename(self, owner_id: str, thread_id: str, title: str) -> bool: ...
    def delete(self, owner_id: str, thread_id: str) -> bool: ...


@runtime_checkable
class EntitlementRepositoryProtocol(Protocol):
    """能力授权持久化契约。"""

    def has_active(
        self,
        *,
        user_id: str,
        capability: Capability,
        now: datetime | None = None,
    ) -> bool: ...

    def grant(
        self,
        *,
        user_id: str,
        capability: Capability,
        source: EntitlementSource,
        created_by: str | None,
        expires_at: datetime | None = None,
        starts_at: datetime | None = None,
    ) -> EntitlementRecord: ...

    def get(self, entitlement_id: str) -> EntitlementRecord | None: ...
    def list_for_user(self, user_id: str) -> list[EntitlementRecord]: ...
    def revoke(self, entitlement_id: str) -> bool: ...


@runtime_checkable
class NoteRepositoryProtocol(Protocol):
    """笔记持久化契约。"""

    def add(self, owner_id: str, title: str, content: str) -> NoteItem: ...
    def list_all(self, owner_id: str) -> list[NoteItem]: ...
    def get_by_id(self, owner_id: str, note_id: int) -> NoteItem | None: ...
    def search(self, owner_id: str, query: str) -> list[NoteItem]: ...

    def update(
        self,
        owner_id: str,
        note_id: int,
        title: str | None = None,
        content: str | None = None,
    ) -> NoteItem | None: ...

    def delete(self, owner_id: str, note_id: int) -> bool: ...


@runtime_checkable
class ProviderCredentialRepositoryProtocol(Protocol):
    """模型凭据持久化契约。"""

    def get(
        self, *, user_id: str, provider: str
    ) -> ProviderCredentialRecord | None: ...

    def list_by_key_version(
        self, key_version: str
    ) -> list[ProviderCredentialRecord]: ...

    def upsert_active(
        self,
        *,
        credential_id: str,
        user_id: str,
        provider: str,
        encrypted_secret: str,
        encryption_key_version: str,
        fingerprint: str,
        masked_suffix: str,
        validated_at: datetime,
    ) -> ProviderCredentialRecord: ...

    def replace_encrypted_secret(
        self,
        *,
        credential_id: str,
        encrypted_secret: str,
        encryption_key_version: str,
    ) -> bool: ...

    def mark_used(self, *, credential_id: str, used_at: datetime) -> None: ...
    def mark_invalid(self, *, credential_id: str) -> None: ...
    def revoke(self, *, user_id: str, provider: str) -> bool: ...
    def delete(self, *, user_id: str, provider: str) -> bool: ...


@runtime_checkable
class QuotaRepositoryProtocol(Protocol):
    """月度模型配额持久化契约。"""

    def get_status(self, user_id: str, period_start: date) -> QuotaStatus: ...

    def set_quota(
        self,
        *,
        user_id: str,
        monthly_request_limit: int | None,
        monthly_token_limit: int | None,
        updated_by: str | None,
    ) -> UserQuota: ...

    def reserve_model_request(self, user_id: str, period_start: date) -> bool: ...
    def add_tokens(self, user_id: str, period_start: date, tokens: int) -> None: ...


@runtime_checkable
class TodoRepositoryProtocol(Protocol):
    """待办持久化契约。"""

    def add(self, owner_id: str, task: str) -> TodoItem: ...
    def list_all(self, owner_id: str) -> list[TodoItem]: ...
    def mark_completed(self, owner_id: str, todo_id: int) -> bool: ...
    def delete(self, owner_id: str, todo_id: int) -> bool: ...


@runtime_checkable
class UsageRepositoryProtocol(Protocol):
    """模型调用事件持久化契约。"""

    def begin(self, event: UsageEvent) -> bool: ...

    def mark_succeeded(
        self,
        *,
        event_id: str,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        completed_at: datetime,
        duration_ms: int,
    ) -> bool: ...

    def mark_failed(
        self,
        *,
        event_id: str,
        error_code: str,
        completed_at: datetime,
        duration_ms: int,
    ) -> bool: ...

    def list_for_user(
        self,
        *,
        user_id: str,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[UsageEvent]: ...

    def summarize(
        self, *, user_id: str, since: datetime, until: datetime
    ) -> UsageSummary: ...

    def summarize_all(self, *, since: datetime, until: datetime) -> dict[str, int]: ...


@runtime_checkable
class UserMemoryRepositoryProtocol(Protocol):
    """用户资料与长期记忆持久化契约。"""

    def get_profile(self, owner_id: str) -> UserProfile | None: ...

    def update_profile(
        self,
        owner_id: str,
        display_name: str | None = None,
        occupation: str | None = None,
        current_goal: str | None = None,
        response_style: str | None = None,
    ) -> UserProfile: ...

    def add_memory(self, owner_id: str, category: str, content: str) -> UserMemory: ...

    def list_recent(self, owner_id: str, limit: int = 20) -> list[UserMemory]: ...
    def search(self, owner_id: str, query: str) -> list[UserMemory]: ...
    def delete_memory(self, owner_id: str, memory_id: int) -> bool: ...
