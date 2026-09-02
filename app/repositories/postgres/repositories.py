"""基于 SQLAlchemy 2 的 PostgreSQL 生产仓储实现。"""
# mypy: disable-error-code=attr-defined

from datetime import UTC, date, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.access.models import (
    Capability,
    EntitlementRecord,
    EntitlementSource,
    EntitlementStatus,
)
from app.auth.errors import RegistrationDeniedError, UsernameUnavailableError
from app.auth.models import (
    InvitationRecord,
    Principal,
    UserRecord,
    UserRole,
    UserStatus,
)
from app.credentials.models import (
    CredentialStatus,
    ModelMode,
    ProviderCredentialRecord,
    ProviderName,
)
from app.database import Database
from app.database_models import (
    AuditEventRow,
    AuthSessionRow,
    ConversationRow,
    EntitlementRow,
    NoteRow,
    ProviderCredentialRow,
    QuotaUsageRow,
    RegistrationInviteRow,
    TodoRow,
    UsageEventRow,
    UserMemoryRow,
    UserProfileRow,
    UserQuotaRow,
    UserRow,
)
from app.domain.models import (
    AuditEvent,
    Conversation,
    NoteItem,
    TodoItem,
    UserMemory,
    UserProfile,
)
from app.quota.models import QuotaStatus, UserQuota
from app.usage.models import UsageEvent, UsageStatus, UsageSummary


class PostgresAuthRepository:
    """使用 PostgreSQL 事务管理账号、Session 和邀请码。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _user(row: UserRow) -> UserRecord:
        return UserRecord(
            id=row.id,
            username=row.username,
            username_normalized=row.username_normalized,
            password_hash=row.password_hash,
            role=cast(UserRole, row.role),
            status=cast(UserStatus, row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def create_user(
        self, *, user_id: str, username: str, password_hash: str, role: str
    ) -> UserRecord:
        clean_username = username.strip()
        if not clean_username:
            raise ValueError("用户名不能为空。")
        if len(clean_username) > 64:
            raise ValueError("用户名不能超过64个字符。")
        if role not in {"admin", "user"}:
            raise ValueError("用户角色无效。")
        timestamp = datetime.now(UTC)
        try:
            with self._database.session() as session:
                row = UserRow(
                    id=user_id,
                    username=clean_username,
                    username_normalized=clean_username.casefold(),
                    password_hash=password_hash,
                    role=role,
                    status="active",
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                session.flush()
                return self._user(row)
        except IntegrityError as error:
            raise ValueError("用户名已经存在。") from error

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self._database.session() as session:
            row = session.scalar(
                select(UserRow).where(
                    UserRow.username_normalized == username.strip().casefold()
                )
            )
            return None if row is None else self._user(row)

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        with self._database.session() as session:
            row = session.get(UserRow, user_id)
            return None if row is None else self._user(row)

    def list_users(self, limit: int = 100) -> list[UserRecord]:
        with self._database.session() as session:
            rows = session.scalars(
                select(UserRow)
                .order_by(UserRow.created_at.desc())
                .limit(min(max(limit, 1), 500))
            ).all()
            return [self._user(row) for row in rows]

    def update_password_hash(self, user_id: str, password_hash: str) -> bool:
        with self._database.session() as session:
            result = session.execute(
                update(UserRow)
                .where(UserRow.id == user_id)
                .values(password_hash=password_hash, updated_at=datetime.now(UTC))
            )
            return bool(result.rowcount)

    def set_user_status(self, user_id: str, status: str) -> bool:
        if status not in {"active", "disabled"}:
            raise ValueError("用户状态无效。")
        timestamp = datetime.now(UTC)
        with self._database.session() as session:
            result = session.execute(
                update(UserRow)
                .where(UserRow.id == user_id)
                .values(status=status, updated_at=timestamp)
            )
            if status == "disabled":
                session.execute(
                    update(AuthSessionRow)
                    .where(
                        AuthSessionRow.user_id == user_id,
                        AuthSessionRow.revoked_at.is_(None),
                    )
                    .values(revoked_at=timestamp)
                )
            return bool(result.rowcount)

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        timestamp = datetime.now(UTC)
        with self._database.session() as session:
            session.add(
                AuthSessionRow(
                    id=session_id,
                    user_id=user_id,
                    token_hash=token_hash,
                    created_at=timestamp,
                    expires_at=expires_at,
                    last_seen_at=timestamp,
                    revoked_at=None,
                )
            )

    def find_principal_by_token_hash(
        self, token_hash: str, now: datetime
    ) -> Principal | None:
        with self._database.session() as session:
            row = session.execute(
                select(AuthSessionRow, UserRow)
                .join(UserRow, UserRow.id == AuthSessionRow.user_id)
                .where(
                    AuthSessionRow.token_hash == token_hash,
                    AuthSessionRow.revoked_at.is_(None),
                    AuthSessionRow.expires_at > now,
                    UserRow.status == "active",
                )
            ).one_or_none()
            if row is None:
                return None
            auth_session, user = row
            return Principal(
                user_id=user.id,
                username=user.username,
                role=cast(UserRole, user.role),
                status=cast(UserStatus, user.status),
                session_id=auth_session.id,
            )

    def touch_session(
        self, session_id: str, now: datetime, minimum_last_seen: datetime
    ) -> None:
        with self._database.session() as session:
            session.execute(
                update(AuthSessionRow)
                .where(
                    AuthSessionRow.id == session_id,
                    AuthSessionRow.revoked_at.is_(None),
                    AuthSessionRow.last_seen_at < minimum_last_seen,
                )
                .values(last_seen_at=now)
            )

    def revoke_session(self, session_id: str) -> bool:
        with self._database.session() as session:
            result = session.execute(
                update(AuthSessionRow)
                .where(
                    AuthSessionRow.id == session_id,
                    AuthSessionRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            return bool(result.rowcount)

    def revoke_all_sessions(self, user_id: str) -> int:
        with self._database.session() as session:
            result = session.execute(
                update(AuthSessionRow)
                .where(
                    AuthSessionRow.user_id == user_id,
                    AuthSessionRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            return int(result.rowcount or 0)

    def delete_expired_sessions(self, now: datetime) -> int:
        with self._database.session() as session:
            result = session.execute(
                delete(AuthSessionRow).where(
                    or_(
                        AuthSessionRow.expires_at <= now,
                        AuthSessionRow.revoked_at.is_not(None),
                    )
                )
            )
            return int(result.rowcount or 0)

    @staticmethod
    def _invitation(
        invite: RegistrationInviteRow,
        created_by_username: str,
        used_by_username: str | None,
    ) -> InvitationRecord:
        return InvitationRecord(
            id=invite.id,
            created_by=invite.created_by,
            created_by_username=created_by_username,
            expires_at=invite.expires_at,
            used_by=invite.used_by,
            used_by_username=used_by_username,
            used_at=invite.used_at,
            revoked_at=invite.revoked_at,
            created_at=invite.created_at,
        )

    def create_invitation(
        self,
        *,
        invitation_id: str,
        code_hash: str,
        created_by: str,
        expires_at: datetime,
    ) -> InvitationRecord:
        with self._database.session() as session:
            session.add(
                RegistrationInviteRow(
                    id=invitation_id,
                    code_hash=code_hash,
                    created_by=created_by,
                    expires_at=expires_at,
                    used_by=None,
                    used_at=None,
                    revoked_at=None,
                    created_at=datetime.now(UTC),
                )
            )
        invitation = self.get_invitation(invitation_id)
        if invitation is None:
            raise RuntimeError("创建邀请码后无法读取记录。")
        return invitation

    def _invitation_query(self) -> object:
        creator = UserRow.__table__.alias("creator")
        used = UserRow.__table__.alias("used")
        return (
            select(
                RegistrationInviteRow,
                creator.c.username.label("created_by_username"),
                used.c.username.label("used_by_username"),
            )
            .join(creator, creator.c.id == RegistrationInviteRow.created_by)
            .outerjoin(used, used.c.id == RegistrationInviteRow.used_by)
        )

    def get_invitation(self, invitation_id: str) -> InvitationRecord | None:
        with self._database.session() as session:
            result = session.execute(
                self._invitation_query().where(
                    RegistrationInviteRow.id == invitation_id
                )
            ).one_or_none()
            if result is None:
                return None
            return self._invitation(result[0], result[1], result[2])

    def list_invitations(self) -> list[InvitationRecord]:
        with self._database.session() as session:
            rows = session.execute(
                self._invitation_query().order_by(
                    RegistrationInviteRow.created_at.desc()
                )
            ).all()
            return [self._invitation(row[0], row[1], row[2]) for row in rows]

    def revoke_invitation(self, invitation_id: str) -> bool:
        with self._database.session() as session:
            result = session.execute(
                update(RegistrationInviteRow)
                .where(
                    RegistrationInviteRow.id == invitation_id,
                    RegistrationInviteRow.used_at.is_(None),
                    RegistrationInviteRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            return bool(result.rowcount)

    def register_with_invitation(
        self,
        *,
        user_id: str,
        username: str,
        password_hash: str,
        invitation_code_hash: str,
        now: datetime,
    ) -> UserRecord:
        clean_username = username.strip()
        if not clean_username or len(clean_username) > 64:
            raise UsernameUnavailableError("用户名不可用。")
        try:
            with self._database.session() as session:
                invitation = session.scalar(
                    select(RegistrationInviteRow)
                    .where(
                        RegistrationInviteRow.code_hash == invitation_code_hash,
                        RegistrationInviteRow.used_at.is_(None),
                        RegistrationInviteRow.revoked_at.is_(None),
                        RegistrationInviteRow.expires_at > now,
                    )
                    .with_for_update()
                )
                if invitation is None:
                    raise RegistrationDeniedError("邀请码无效或已经失效。")
                row = UserRow(
                    id=user_id,
                    username=clean_username,
                    username_normalized=clean_username.casefold(),
                    password_hash=password_hash,
                    role="user",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                invitation.used_by = user_id
                invitation.used_at = now
                session.flush()
                return self._user(row)
        except IntegrityError as error:
            raise UsernameUnavailableError("用户名不可用。") from error


class PostgresTodoRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _item(row: TodoRow) -> TodoItem:
        return TodoItem(
            id=row.id,
            owner_id=row.owner_id,
            task=row.task,
            is_completed=row.is_completed,
            created_at=row.created_at.isoformat(),
        )

    def add(self, owner_id: str, task: str) -> TodoItem:
        clean_task = task.strip()
        if not clean_task:
            raise ValueError("Todo content cannot be empty.")
        with self._database.session() as session:
            row = TodoRow(
                owner_id=owner_id,
                task=clean_task,
                is_completed=False,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return self._item(row)

    def list_all(self, owner_id: str) -> list[TodoItem]:
        with self._database.session() as session:
            rows = session.scalars(
                select(TodoRow).where(TodoRow.owner_id == owner_id).order_by(TodoRow.id)
            ).all()
            return [self._item(row) for row in rows]

    def mark_completed(self, owner_id: str, todo_id: int) -> bool:
        with self._database.session() as session:
            result = session.execute(
                update(TodoRow)
                .where(TodoRow.id == todo_id, TodoRow.owner_id == owner_id)
                .values(is_completed=True)
            )
            return bool(result.rowcount)

    def delete(self, owner_id: str, todo_id: int) -> bool:
        with self._database.session() as session:
            result = session.execute(
                delete(TodoRow).where(
                    TodoRow.id == todo_id, TodoRow.owner_id == owner_id
                )
            )
            return bool(result.rowcount)


class PostgresNoteRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _item(row: NoteRow) -> NoteItem:
        return NoteItem(
            id=row.id,
            owner_id=row.owner_id,
            title=row.title,
            content=row.content,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )

    def add(self, owner_id: str, title: str, content: str) -> NoteItem:
        clean_title, clean_content = title.strip(), content.strip()
        if not clean_title:
            raise ValueError("Note title cannot be empty.")
        if not clean_content:
            raise ValueError("Note content cannot be empty.")
        timestamp = datetime.now(UTC)
        with self._database.session() as session:
            row = NoteRow(
                owner_id=owner_id,
                title=clean_title,
                content=clean_content,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(row)
            session.flush()
            return self._item(row)

    def list_all(self, owner_id: str) -> list[NoteItem]:
        with self._database.session() as session:
            rows = session.scalars(
                select(NoteRow)
                .where(NoteRow.owner_id == owner_id)
                .order_by(NoteRow.updated_at.desc(), NoteRow.id.desc())
            ).all()
            return [self._item(row) for row in rows]

    def get_by_id(self, owner_id: str, note_id: int) -> NoteItem | None:
        with self._database.session() as session:
            row = session.scalar(
                select(NoteRow).where(
                    NoteRow.id == note_id, NoteRow.owner_id == owner_id
                )
            )
            return None if row is None else self._item(row)

    def search(self, owner_id: str, query: str) -> list[NoteItem]:
        clean_query = query.strip()
        if not clean_query:
            return []
        pattern = f"%{clean_query}%"
        with self._database.session() as session:
            rows = session.scalars(
                select(NoteRow)
                .where(
                    NoteRow.owner_id == owner_id,
                    or_(NoteRow.title.ilike(pattern), NoteRow.content.ilike(pattern)),
                )
                .order_by(NoteRow.updated_at.desc(), NoteRow.id.desc())
            ).all()
            return [self._item(row) for row in rows]

    def update(
        self,
        owner_id: str,
        note_id: int,
        title: str | None = None,
        content: str | None = None,
    ) -> NoteItem | None:
        with self._database.session() as session:
            row = session.scalar(
                select(NoteRow)
                .where(NoteRow.id == note_id, NoteRow.owner_id == owner_id)
                .with_for_update()
            )
            if row is None:
                return None
            if title is not None:
                row.title = title.strip()
                if not row.title:
                    raise ValueError("Note title cannot be empty.")
            if content is not None:
                row.content = content.strip()
                if not row.content:
                    raise ValueError("Note content cannot be empty.")
            row.updated_at = datetime.now(UTC)
            session.flush()
            return self._item(row)

    def delete(self, owner_id: str, note_id: int) -> bool:
        with self._database.session() as session:
            result = session.execute(
                delete(NoteRow).where(
                    NoteRow.id == note_id, NoteRow.owner_id == owner_id
                )
            )
            return bool(result.rowcount)


class PostgresConversationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _conversation(row: ConversationRow) -> Conversation:
        return Conversation(
            owner_id=row.owner_id,
            thread_id=row.thread_id,
            title=row.title,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def record_message(self, owner_id: str, thread_id: str, first_message: str) -> None:
        timestamp = datetime.now(UTC)
        statement = insert(ConversationRow).values(
            owner_id=owner_id,
            thread_id=thread_id,
            title=self._build_title(first_message),
            created_at=timestamp,
            updated_at=timestamp,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["owner_id", "thread_id"],
            set_={"updated_at": timestamp},
        )
        with self._database.session() as session:
            session.execute(statement)

    def touch(self, owner_id: str, thread_id: str) -> bool:
        with self._database.session() as session:
            result = session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.owner_id == owner_id,
                    ConversationRow.thread_id == thread_id,
                )
                .values(updated_at=datetime.now(UTC))
            )
            return bool(result.rowcount)

    def list_conversations(self, owner_id: str, limit: int = 50) -> list[Conversation]:
        if limit <= 0:
            raise ValueError("会话列表数量必须大于0")
        with self._database.session() as session:
            rows = session.scalars(
                select(ConversationRow)
                .where(ConversationRow.owner_id == owner_id)
                .order_by(
                    ConversationRow.updated_at.desc(),
                    ConversationRow.created_at.desc(),
                )
                .limit(limit)
            ).all()
            return [self._conversation(row) for row in rows]

    def get(self, owner_id: str, thread_id: str) -> Conversation | None:
        with self._database.session() as session:
            row = session.get(ConversationRow, (owner_id, thread_id))
            return None if row is None else self._conversation(row)

    def rename(self, owner_id: str, thread_id: str, title: str) -> bool:
        clean_title = " ".join(title.split())
        if not clean_title:
            raise ValueError("会话标题不能为空")
        if len(clean_title) > 80:
            raise ValueError("会话标题不能超过80个字符")
        with self._database.session() as session:
            result = session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.owner_id == owner_id,
                    ConversationRow.thread_id == thread_id,
                )
                .values(title=clean_title, updated_at=datetime.now(UTC))
            )
            return bool(result.rowcount)

    def delete(self, owner_id: str, thread_id: str) -> bool:
        with self._database.session() as session:
            result = session.execute(
                delete(ConversationRow).where(
                    ConversationRow.owner_id == owner_id,
                    ConversationRow.thread_id == thread_id,
                )
            )
            return bool(result.rowcount)


class PostgresUserMemoryRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _profile(row: UserProfileRow) -> UserProfile:
        return UserProfile(
            owner_id=row.owner_id,
            display_name=row.display_name,
            occupation=row.occupation,
            current_goal=row.current_goal,
            response_style=row.response_style,
            updated_at=row.updated_at.isoformat(),
        )

    @staticmethod
    def _memory(row: UserMemoryRow) -> UserMemory:
        return UserMemory(
            id=row.id,
            owner_id=row.owner_id,
            category=row.category,
            content=row.content,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )

    def get_profile(self, owner_id: str) -> UserProfile | None:
        with self._database.session() as session:
            row = session.get(UserProfileRow, owner_id)
            return None if row is None else self._profile(row)

    def update_profile(
        self,
        owner_id: str,
        display_name: str | None = None,
        occupation: str | None = None,
        current_goal: str | None = None,
        response_style: str | None = None,
    ) -> UserProfile:
        values = (display_name, occupation, current_goal, response_style)
        if all(value is None for value in values):
            raise ValueError("At least one profile field is required.")
        timestamp = datetime.now(UTC)
        with self._database.session() as session:
            row = session.get(UserProfileRow, owner_id)
            if row is None:
                row = UserProfileRow(
                    owner_id=owner_id,
                    display_name=None,
                    occupation=None,
                    current_goal=None,
                    response_style=None,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
            row.display_name = self._merge_field(
                display_name, row.display_name, "display name"
            )
            row.occupation = self._merge_field(occupation, row.occupation, "occupation")
            row.current_goal = self._merge_field(
                current_goal, row.current_goal, "current goal"
            )
            row.response_style = self._merge_field(
                response_style, row.response_style, "response style"
            )
            row.updated_at = timestamp
            session.flush()
            return self._profile(row)

    def add_memory(self, owner_id: str, category: str, content: str) -> UserMemory:
        clean_category, clean_content = category.strip(), content.strip()
        if not clean_category:
            raise ValueError("Memory category cannot be empty.")
        if not clean_content:
            raise ValueError("Memory content cannot be empty.")
        if len(clean_category) > 50:
            raise ValueError("Memory category is too long.")
        if len(clean_content) > 500:
            raise ValueError("Memory content is too long.")
        timestamp = datetime.now(UTC)
        statement = (
            insert(UserMemoryRow)
            .values(
                owner_id=owner_id,
                category=clean_category,
                content=clean_content,
                created_at=timestamp,
                updated_at=timestamp,
            )
            .on_conflict_do_nothing(index_elements=["owner_id", "category", "content"])
            .returning(UserMemoryRow.id)
        )
        with self._database.session() as session:
            memory_id = session.scalar(statement)
            if memory_id is None:
                row = session.scalar(
                    select(UserMemoryRow).where(
                        UserMemoryRow.owner_id == owner_id,
                        UserMemoryRow.category == clean_category,
                        UserMemoryRow.content == clean_content,
                    )
                )
            else:
                row = session.get(UserMemoryRow, memory_id)
            if row is None:
                raise RuntimeError("保存长期记忆后无法读取记录。")
            return self._memory(row)

    def list_recent(self, owner_id: str, limit: int = 20) -> list[UserMemory]:
        safe_limit = max(1, min(limit, 100))
        with self._database.session() as session:
            rows = session.scalars(
                select(UserMemoryRow)
                .where(UserMemoryRow.owner_id == owner_id)
                .order_by(UserMemoryRow.updated_at.desc(), UserMemoryRow.id.desc())
                .limit(safe_limit)
            ).all()
            return [self._memory(row) for row in rows]

    def search(self, owner_id: str, query: str) -> list[UserMemory]:
        clean_query = query.strip()
        if not clean_query:
            return []
        pattern = f"%{clean_query}%"
        with self._database.session() as session:
            rows = session.scalars(
                select(UserMemoryRow)
                .where(
                    UserMemoryRow.owner_id == owner_id,
                    or_(
                        UserMemoryRow.category.ilike(pattern),
                        UserMemoryRow.content.ilike(pattern),
                    ),
                )
                .order_by(UserMemoryRow.updated_at.desc(), UserMemoryRow.id.desc())
            ).all()
            return [self._memory(row) for row in rows]

    def delete_memory(self, owner_id: str, memory_id: int) -> bool:
        with self._database.session() as session:
            result = session.execute(
                delete(UserMemoryRow).where(
                    UserMemoryRow.id == memory_id,
                    UserMemoryRow.owner_id == owner_id,
                )
            )
            return bool(result.rowcount)


class PostgresProviderCredentialRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _record(row: ProviderCredentialRow) -> ProviderCredentialRecord:
        return ProviderCredentialRecord(
            id=row.id,
            user_id=row.user_id,
            provider=cast(ProviderName, row.provider),
            encrypted_secret=row.encrypted_secret,
            encryption_key_version=row.encryption_key_version,
            fingerprint=row.fingerprint,
            masked_suffix=row.masked_suffix,
            status=cast(CredentialStatus, row.status),
            validated_at=row.validated_at,
            last_used_at=row.last_used_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            revoked_at=row.revoked_at,
        )

    def get(self, *, user_id: str, provider: str) -> ProviderCredentialRecord | None:
        with self._database.session() as session:
            row = session.scalar(
                select(ProviderCredentialRow).where(
                    ProviderCredentialRow.user_id == user_id,
                    ProviderCredentialRow.provider == provider,
                )
            )
            return None if row is None else self._record(row)

    def list_by_key_version(self, key_version: str) -> list[ProviderCredentialRecord]:
        with self._database.session() as session:
            rows = session.scalars(
                select(ProviderCredentialRow)
                .where(
                    ProviderCredentialRow.encryption_key_version == key_version,
                    ProviderCredentialRow.encrypted_secret.is_not(None),
                )
                .order_by(ProviderCredentialRow.created_at)
            ).all()
            return [self._record(row) for row in rows]

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
    ) -> ProviderCredentialRecord:
        timestamp = datetime.now(UTC)
        statement = insert(ProviderCredentialRow).values(
            id=credential_id,
            user_id=user_id,
            provider=provider,
            encrypted_secret=encrypted_secret,
            encryption_key_version=encryption_key_version,
            fingerprint=fingerprint,
            masked_suffix=masked_suffix,
            status="active",
            validated_at=validated_at,
            last_used_at=None,
            created_at=timestamp,
            updated_at=timestamp,
            revoked_at=None,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_credentials_user_provider",
            set_={
                "encrypted_secret": encrypted_secret,
                "encryption_key_version": encryption_key_version,
                "fingerprint": fingerprint,
                "masked_suffix": masked_suffix,
                "status": "active",
                "validated_at": validated_at,
                "last_used_at": None,
                "updated_at": timestamp,
                "revoked_at": None,
            },
        )
        with self._database.session() as session:
            session.execute(statement)
        record = self.get(user_id=user_id, provider=provider)
        if record is None:
            raise RuntimeError("保存模型凭据后无法读取记录。")
        return record

    def replace_encrypted_secret(
        self,
        *,
        credential_id: str,
        encrypted_secret: str,
        encryption_key_version: str,
    ) -> bool:
        with self._database.session() as session:
            result = session.execute(
                update(ProviderCredentialRow)
                .where(
                    ProviderCredentialRow.id == credential_id,
                    ProviderCredentialRow.encrypted_secret.is_not(None),
                )
                .values(
                    encrypted_secret=encrypted_secret,
                    encryption_key_version=encryption_key_version,
                    updated_at=datetime.now(UTC),
                )
            )
            return bool(result.rowcount)

    def mark_used(self, *, credential_id: str, used_at: datetime) -> None:
        with self._database.session() as session:
            session.execute(
                update(ProviderCredentialRow)
                .where(
                    ProviderCredentialRow.id == credential_id,
                    ProviderCredentialRow.status == "active",
                )
                .values(last_used_at=used_at, updated_at=used_at)
            )

    def mark_invalid(self, *, credential_id: str) -> None:
        with self._database.session() as session:
            session.execute(
                update(ProviderCredentialRow)
                .where(
                    ProviderCredentialRow.id == credential_id,
                    ProviderCredentialRow.status == "active",
                )
                .values(status="invalid", updated_at=datetime.now(UTC))
            )

    def revoke(self, *, user_id: str, provider: str) -> bool:
        timestamp = datetime.now(UTC)
        with self._database.session() as session:
            result = session.execute(
                update(ProviderCredentialRow)
                .where(
                    ProviderCredentialRow.user_id == user_id,
                    ProviderCredentialRow.provider == provider,
                    ProviderCredentialRow.status != "revoked",
                )
                .values(
                    encrypted_secret=None,
                    encryption_key_version=None,
                    fingerprint=None,
                    status="revoked",
                    updated_at=timestamp,
                    revoked_at=timestamp,
                )
            )
            return bool(result.rowcount)

    def delete(self, *, user_id: str, provider: str) -> bool:
        with self._database.session() as session:
            result = session.execute(
                delete(ProviderCredentialRow).where(
                    ProviderCredentialRow.user_id == user_id,
                    ProviderCredentialRow.provider == provider,
                )
            )
            return bool(result.rowcount)


class PostgresEntitlementRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _record(row: EntitlementRow) -> EntitlementRecord:
        return EntitlementRecord(
            id=row.id,
            user_id=row.user_id,
            capability=Capability(row.capability),
            source=EntitlementSource(row.source),
            status=EntitlementStatus(row.status),
            starts_at=row.starts_at,
            expires_at=row.expires_at,
            created_by=row.created_by,
            created_at=row.created_at,
            revoked_at=row.revoked_at,
        )

    def has_active(
        self,
        *,
        user_id: str,
        capability: Capability,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        with self._database.session() as session:
            result = session.scalar(
                select(EntitlementRow.id)
                .where(
                    EntitlementRow.user_id == user_id,
                    EntitlementRow.capability == capability.value,
                    EntitlementRow.status == "active",
                    EntitlementRow.starts_at <= current,
                    or_(
                        EntitlementRow.expires_at.is_(None),
                        EntitlementRow.expires_at > current,
                    ),
                )
                .limit(1)
            )
            return result is not None

    def grant(
        self,
        *,
        user_id: str,
        capability: Capability,
        source: EntitlementSource,
        created_by: str | None,
        expires_at: datetime | None = None,
        starts_at: datetime | None = None,
    ) -> EntitlementRecord:
        timestamp = datetime.now(UTC)
        row = EntitlementRow(
            id=str(uuid4()),
            user_id=user_id,
            capability=capability.value,
            source=source.value,
            status="active",
            starts_at=starts_at or timestamp,
            expires_at=expires_at,
            created_by=created_by,
            created_at=timestamp,
            revoked_at=None,
        )
        with self._database.session() as session:
            session.add(row)
            session.flush()
            return self._record(row)

    def get(self, entitlement_id: str) -> EntitlementRecord | None:
        with self._database.session() as session:
            row = session.get(EntitlementRow, entitlement_id)
            return None if row is None else self._record(row)

    def list_for_user(self, user_id: str) -> list[EntitlementRecord]:
        with self._database.session() as session:
            rows = session.scalars(
                select(EntitlementRow)
                .where(EntitlementRow.user_id == user_id)
                .order_by(EntitlementRow.created_at.desc())
            ).all()
            return [self._record(row) for row in rows]

    def revoke(self, entitlement_id: str) -> bool:
        with self._database.session() as session:
            result = session.execute(
                update(EntitlementRow)
                .where(
                    EntitlementRow.id == entitlement_id,
                    EntitlementRow.status == "active",
                )
                .values(status="revoked", revoked_at=datetime.now(UTC))
            )
            return bool(result.rowcount)


class PostgresQuotaRepository:
    """使用事务 advisory lock 原子维护跨实例配额计数。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _quota(row: UserQuotaRow | None, user_id: str) -> UserQuota:
        if row is None:
            return UserQuota(user_id, None, None, None, datetime.now(UTC))
        return UserQuota(
            user_id=row.user_id,
            monthly_request_limit=row.monthly_request_limit,
            monthly_token_limit=row.monthly_token_limit,
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _lock(session: Session, user_id: str, period_start: date) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"quota:{user_id}:{period_start.isoformat()}"},
        )

    def get_status(self, user_id: str, period_start: date) -> QuotaStatus:
        with self._database.session() as session:
            quota = self._quota(session.get(UserQuotaRow, user_id), user_id)
            usage = session.get(QuotaUsageRow, (user_id, period_start))
            return QuotaStatus(
                quota=quota,
                period_start=period_start,
                request_count=0 if usage is None else usage.request_count,
                token_count=0 if usage is None else usage.token_count,
            )

    def set_quota(
        self,
        *,
        user_id: str,
        monthly_request_limit: int | None,
        monthly_token_limit: int | None,
        updated_by: str | None,
    ) -> UserQuota:
        self._validate_limit(monthly_request_limit)
        self._validate_limit(monthly_token_limit)
        updated_at = datetime.now(UTC)
        statement = (
            insert(UserQuotaRow)
            .values(
                user_id=user_id,
                monthly_request_limit=monthly_request_limit,
                monthly_token_limit=monthly_token_limit,
                updated_by=updated_by,
                updated_at=updated_at,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "monthly_request_limit": monthly_request_limit,
                    "monthly_token_limit": monthly_token_limit,
                    "updated_by": updated_by,
                    "updated_at": updated_at,
                },
            )
        )
        with self._database.session() as session:
            session.execute(statement)
        return UserQuota(
            user_id,
            monthly_request_limit,
            monthly_token_limit,
            updated_by,
            updated_at,
        )

    def reserve_model_request(self, user_id: str, period_start: date) -> bool:
        with self._database.session() as session:
            self._lock(session, user_id, period_start)
            quota = self._quota(session.get(UserQuotaRow, user_id), user_id)
            usage = session.get(QuotaUsageRow, (user_id, period_start))
            requests = 0 if usage is None else usage.request_count
            tokens = 0 if usage is None else usage.token_count
            if (
                quota.monthly_request_limit is not None
                and requests >= quota.monthly_request_limit
            ) or (
                quota.monthly_token_limit is not None
                and tokens >= quota.monthly_token_limit
            ):
                return False
            if usage is None:
                session.add(
                    QuotaUsageRow(
                        user_id=user_id,
                        period_start=period_start,
                        request_count=1,
                        token_count=0,
                    )
                )
            else:
                usage.request_count += 1
            return True

    def add_tokens(self, user_id: str, period_start: date, tokens: int) -> None:
        if tokens <= 0:
            return
        with self._database.session() as session:
            self._lock(session, user_id, period_start)
            usage = session.get(QuotaUsageRow, (user_id, period_start))
            if usage is None:
                session.add(
                    QuotaUsageRow(
                        user_id=user_id,
                        period_start=period_start,
                        request_count=0,
                        token_count=tokens,
                    )
                )
            else:
                usage.token_count += tokens


class PostgresUsageRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _event(row: UsageEventRow) -> UsageEvent:
        return UsageEvent(
            event_id=row.event_id,
            request_id=row.request_id,
            user_id=row.user_id,
            thread_id=row.thread_id,
            provider=row.provider,
            model=row.model,
            credential_mode=cast(ModelMode, row.credential_mode),
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            total_tokens=row.total_tokens,
            status=cast(UsageStatus, row.status),
            error_code=row.error_code,
            started_at=row.started_at,
            completed_at=row.completed_at,
            duration_ms=row.duration_ms,
        )

    def begin(self, event: UsageEvent) -> bool:
        statement = (
            insert(UsageEventRow)
            .values(
                event_id=event.event_id,
                request_id=event.request_id,
                user_id=event.user_id,
                thread_id=event.thread_id,
                provider=event.provider,
                model=event.model,
                credential_mode=event.credential_mode,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                status="started",
                error_code=None,
                started_at=event.started_at,
                completed_at=None,
                duration_ms=None,
            )
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        with self._database.session() as session:
            result = session.execute(statement)
            return bool(result.rowcount)

    def mark_succeeded(
        self,
        *,
        event_id: str,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        completed_at: datetime,
        duration_ms: int,
    ) -> bool:
        with self._database.session() as session:
            result = session.execute(
                update(UsageEventRow)
                .where(
                    UsageEventRow.event_id == event_id,
                    UsageEventRow.status == "started",
                )
                .values(
                    status="succeeded",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                )
            )
            return bool(result.rowcount)

    def mark_failed(
        self,
        *,
        event_id: str,
        error_code: str,
        completed_at: datetime,
        duration_ms: int,
    ) -> bool:
        with self._database.session() as session:
            result = session.execute(
                update(UsageEventRow)
                .where(
                    UsageEventRow.event_id == event_id,
                    UsageEventRow.status == "started",
                )
                .values(
                    status="failed",
                    error_code=error_code,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                )
            )
            return bool(result.rowcount)

    def list_for_user(
        self, *, user_id: str, limit: int = 50, before: datetime | None = None
    ) -> list[UsageEvent]:
        statement = select(UsageEventRow).where(UsageEventRow.user_id == user_id)
        if before is not None:
            statement = statement.where(UsageEventRow.started_at < before)
        statement = statement.order_by(
            UsageEventRow.started_at.desc(), UsageEventRow.event_id.desc()
        ).limit(min(max(limit, 1), 100))
        with self._database.session() as session:
            return [self._event(row) for row in session.scalars(statement).all()]

    def summarize(
        self, *, user_id: str, since: datetime, until: datetime
    ) -> UsageSummary:
        conditions = (
            UsageEventRow.user_id == user_id,
            UsageEventRow.started_at >= since,
            UsageEventRow.started_at < until,
        )
        with self._database.session() as session:
            row = session.execute(
                select(
                    func.count(func.distinct(UsageEventRow.request_id)),
                    func.count().filter(UsageEventRow.status == "succeeded"),
                    func.count().filter(UsageEventRow.status == "failed"),
                    func.coalesce(func.sum(UsageEventRow.input_tokens), 0),
                    func.coalesce(func.sum(UsageEventRow.output_tokens), 0),
                    func.coalesce(func.sum(UsageEventRow.total_tokens), 0),
                    func.count().filter(
                        UsageEventRow.status == "succeeded",
                        UsageEventRow.credential_mode == "BYOK",
                    ),
                    func.count().filter(
                        UsageEventRow.status == "succeeded",
                        UsageEventRow.credential_mode == "PLATFORM",
                    ),
                ).where(*conditions)
            ).one()
        return UsageSummary(
            since=since,
            until=until,
            requests=int(row[0] or 0),
            successful_calls=int(row[1] or 0),
            failed_calls=int(row[2] or 0),
            input_tokens=int(row[3] or 0),
            output_tokens=int(row[4] or 0),
            total_tokens=int(row[5] or 0),
            byok_calls=int(row[6] or 0),
            platform_calls=int(row[7] or 0),
        )

    def summarize_all(self, *, since: datetime, until: datetime) -> dict[str, int]:
        conditions = (
            UsageEventRow.started_at >= since,
            UsageEventRow.started_at < until,
        )
        with self._database.session() as session:
            row = session.execute(
                select(
                    func.count(func.distinct(UsageEventRow.user_id)),
                    func.count(func.distinct(UsageEventRow.request_id)),
                    func.count().filter(UsageEventRow.status == "succeeded"),
                    func.count().filter(UsageEventRow.status == "failed"),
                    func.coalesce(func.sum(UsageEventRow.total_tokens), 0),
                    func.count().filter(
                        UsageEventRow.status == "succeeded",
                        UsageEventRow.credential_mode == "BYOK",
                    ),
                    func.count().filter(
                        UsageEventRow.status == "succeeded",
                        UsageEventRow.credential_mode == "PLATFORM",
                    ),
                ).where(*conditions)
            ).one()
        keys = (
            "active_users",
            "requests",
            "successful_calls",
            "failed_calls",
            "total_tokens",
            "byok_calls",
            "platform_calls",
        )
        return {key: int(row[index] or 0) for index, key in enumerate(keys)}


class PostgresAuditRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def record(
        self,
        *,
        request_id: str,
        user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
    ) -> None:
        with self._database.session() as session:
            session.add(
                AuditEventRow(
                    id=str(uuid4()),
                    request_id=request_id,
                    user_id=user_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    outcome=outcome,
                    created_at=datetime.now(UTC),
                )
            )

    def list_recent(
        self, *, limit: int = 100, user_id: str | None = None
    ) -> list[AuditEvent]:
        statement = select(AuditEventRow)
        if user_id is not None:
            statement = statement.where(AuditEventRow.user_id == user_id)
        statement = statement.order_by(AuditEventRow.created_at.desc()).limit(
            min(max(limit, 1), 500)
        )
        with self._database.session() as session:
            rows = session.scalars(statement).all()
            return [
                AuditEvent(
                    id=row.id,
                    request_id=row.request_id,
                    user_id=row.user_id,
                    action=row.action,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    outcome=row.outcome,
                    created_at=row.created_at,
                )
                for row in rows
            ]
