"""持久化用户账号和认证 Session。"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app.auth.errors import RegistrationDeniedError, UsernameUnavailableError
from app.auth.models import InvitationRecord, Principal, UserRecord


class AuthRepository:
    """管理 SQLite 中的用户和 Session。"""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        password_hash: str,
        role: str,
    ) -> UserRecord:
        """创建启用状态的用户。"""
        clean_username = username.strip()
        normalized = clean_username.casefold()
        timestamp = datetime.now(UTC).isoformat()

        if not clean_username:
            raise ValueError("用户名不能为空。")
        if len(clean_username) > 64:
            raise ValueError("用户名不能超过64个字符。")
        if role not in {"admin", "user"}:
            raise ValueError("用户角色无效。")

        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        id, username, username_normalized, password_hash,
                        role, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        user_id,
                        clean_username,
                        normalized,
                        password_hash,
                        role,
                        timestamp,
                        timestamp,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("用户名已经存在。") from error

        user = self.get_user_by_username(clean_username)
        if user is None:
            raise RuntimeError("创建用户后无法读取用户记录。")
        return user

    def get_user_by_username(self, username: str) -> UserRecord | None:
        """按不区分大小写的规范化用户名读取用户。"""
        normalized = username.strip().casefold()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, username, username_normalized, password_hash,
                       role, status, created_at, updated_at
                FROM users
                WHERE username_normalized = ?
                """,
                (normalized,),
            ).fetchone()
        return None if row is None else self._row_to_user(row)

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        """按内部不可变 ID 读取用户。"""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, username, username_normalized, password_hash,
                       role, status, created_at, updated_at
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return None if row is None else self._row_to_user(row)

    def update_password_hash(self, user_id: str, password_hash: str) -> bool:
        """替换用户密码哈希。"""
        timestamp = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET password_hash = ?, updated_at = ?
                WHERE id = ?
                """,
                (password_hash, timestamp, user_id),
            )
            return cursor.rowcount > 0

    def set_user_status(self, user_id: str, status: str) -> bool:
        """启用或禁用用户，并在禁用时撤销全部 Session。"""
        if status not in {"active", "disabled"}:
            raise ValueError("用户状态无效。")
        timestamp = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, timestamp, user_id),
            )
            if status == "disabled":
                connection.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = ?
                    WHERE user_id = ? AND revoked_at IS NULL
                    """,
                    (timestamp, user_id),
                )
            return cursor.rowcount > 0

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        """保存 Session Token 哈希，绝不保存原始 Token。"""
        timestamp = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO auth_sessions (
                    id, user_id, token_hash, created_at,
                    expires_at, last_seen_at, revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    session_id,
                    user_id,
                    token_hash,
                    timestamp,
                    expires_at.isoformat(),
                    timestamp,
                ),
            )

    def find_principal_by_token_hash(
        self,
        token_hash: str,
        now: datetime,
    ) -> Principal | None:
        """读取有效 Session 对应的启用用户。"""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT sessions.id AS session_id, users.id AS user_id,
                       users.username, users.role, users.status
                FROM auth_sessions AS sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ?
                  AND sessions.revoked_at IS NULL
                  AND sessions.expires_at > ?
                  AND users.status = 'active'
                """,
                (token_hash, now.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return Principal(
            user_id=row["user_id"],
            username=row["username"],
            role=row["role"],
            status=row["status"],
            session_id=row["session_id"],
        )

    def touch_session(
        self,
        session_id: str,
        now: datetime,
        minimum_last_seen: datetime,
    ) -> None:
        """按最小时间间隔刷新 Session 最后活动时间。"""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE auth_sessions
                SET last_seen_at = ?
                WHERE id = ? AND revoked_at IS NULL AND last_seen_at < ?
                """,
                (now.isoformat(), session_id, minimum_last_seen.isoformat()),
            )

    def revoke_session(self, session_id: str) -> bool:
        """撤销当前 Session。"""
        timestamp = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE id = ? AND revoked_at IS NULL
                """,
                (timestamp, session_id),
            )
            return cursor.rowcount > 0

    def revoke_all_sessions(self, user_id: str) -> int:
        """撤销一个用户的全部有效 Session。"""
        timestamp = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (timestamp, user_id),
            )
            return cursor.rowcount

    def delete_expired_sessions(self, now: datetime) -> int:
        """删除已经过期或撤销的 Session。"""
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                DELETE FROM auth_sessions
                WHERE expires_at <= ? OR revoked_at IS NOT NULL
                """,
                (now.isoformat(),),
            )
            return cursor.rowcount

    def create_invitation(
        self,
        *,
        invitation_id: str,
        code_hash: str,
        created_by: str,
        expires_at: datetime,
    ) -> InvitationRecord:
        """保存一次性邀请码摘要。"""
        created_at = datetime.now(UTC)

        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO registration_invites (
                    id, code_hash, created_by, expires_at,
                    used_by, used_at, revoked_at, created_at
                )
                VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (
                    invitation_id,
                    code_hash,
                    created_by,
                    expires_at.isoformat(),
                    created_at.isoformat(),
                ),
            )

        invitation = self.get_invitation(invitation_id)
        if invitation is None:
            raise RuntimeError("创建邀请码后无法读取记录。")
        return invitation

    def get_invitation(
        self,
        invitation_id: str,
    ) -> InvitationRecord | None:
        """按 ID 查询邀请码，不返回邀请码摘要。"""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT invites.id, invites.created_by,
                       creators.username AS created_by_username,
                       invites.expires_at, invites.used_by,
                       users.username AS used_by_username,
                       invites.used_at, invites.revoked_at,
                       invites.created_at
                FROM registration_invites AS invites
                JOIN users AS creators ON creators.id = invites.created_by
                LEFT JOIN users ON users.id = invites.used_by
                WHERE invites.id = ?
                """,
                (invitation_id,),
            ).fetchone()
        return None if row is None else self._row_to_invitation(row)

    def list_invitations(self) -> list[InvitationRecord]:
        """返回管理员可见的邀请码状态列表。"""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT invites.id, invites.created_by,
                       creators.username AS created_by_username,
                       invites.expires_at, invites.used_by,
                       users.username AS used_by_username,
                       invites.used_at, invites.revoked_at,
                       invites.created_at
                FROM registration_invites AS invites
                JOIN users AS creators ON creators.id = invites.created_by
                LEFT JOIN users ON users.id = invites.used_by
                ORDER BY invites.created_at DESC
                """
            ).fetchall()
        return [self._row_to_invitation(row) for row in rows]

    def revoke_invitation(self, invitation_id: str) -> bool:
        """撤销尚未使用的邀请码。"""
        revoked_at = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE registration_invites
                SET revoked_at = ?
                WHERE id = ? AND used_at IS NULL AND revoked_at IS NULL
                """,
                (revoked_at, invitation_id),
            )
            return cursor.rowcount > 0

    def register_with_invitation(
        self,
        *,
        user_id: str,
        username: str,
        password_hash: str,
        invitation_code_hash: str,
        now: datetime,
    ) -> UserRecord:
        """在同一事务中创建普通用户并消费一次性邀请码。"""
        clean_username = username.strip()
        normalized_username = clean_username.casefold()
        if not clean_username or len(clean_username) > 64:
            raise UsernameUnavailableError("用户名不可用。")

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            invitation = connection.execute(
                """
                SELECT id
                FROM registration_invites
                WHERE code_hash = ?
                  AND used_at IS NULL
                  AND revoked_at IS NULL
                  AND expires_at > ?
                """,
                (invitation_code_hash, now.isoformat()),
            ).fetchone()
            if invitation is None:
                raise RegistrationDeniedError("邀请码无效或已经失效。")

            try:
                connection.execute(
                    """
                    INSERT INTO users (
                        id, username, username_normalized, password_hash,
                        role, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, 'user', 'active', ?, ?)
                    """,
                    (
                        user_id,
                        clean_username,
                        normalized_username,
                        password_hash,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise UsernameUnavailableError("用户名不可用。") from error

            cursor = connection.execute(
                """
                UPDATE registration_invites
                SET used_by = ?, used_at = ?
                WHERE id = ?
                  AND used_at IS NULL
                  AND revoked_at IS NULL
                  AND expires_at > ?
                """,
                (
                    user_id,
                    now.isoformat(),
                    invitation["id"],
                    now.isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                raise RegistrationDeniedError("邀请码无效或已经失效。")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("注册成功后无法读取用户记录。")
        return user

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_database(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_normalized TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id
                ON auth_sessions (user_id);

                CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at
                ON auth_sessions (expires_at);

                CREATE TABLE IF NOT EXISTS registration_invites (
                    id TEXT PRIMARY KEY,
                    code_hash TEXT NOT NULL UNIQUE,
                    created_by TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_by TEXT,
                    used_at TEXT,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (created_by) REFERENCES users (id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY (used_by) REFERENCES users (id)
                        ON DELETE SET NULL,
                    CHECK (
                        (used_by IS NULL AND used_at IS NULL)
                        OR
                        (used_by IS NOT NULL AND used_at IS NOT NULL)
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_registration_invites_created
                ON registration_invites (created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_registration_invites_expires
                ON registration_invites (expires_at);
                """
            )

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> UserRecord:
        return UserRecord(
            id=row["id"],
            username=row["username"],
            username_normalized=row["username_normalized"],
            password_hash=row["password_hash"],
            role=row["role"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_invitation(row: sqlite3.Row) -> InvitationRecord:
        """将 SQLite 行转换为邀请码记录。"""
        return InvitationRecord(
            id=row["id"],
            created_by=row["created_by"],
            created_by_username=row["created_by_username"],
            expires_at=datetime.fromisoformat(row["expires_at"]),
            used_by=row["used_by"],
            used_by_username=row["used_by_username"],
            used_at=(
                None
                if row["used_at"] is None
                else datetime.fromisoformat(row["used_at"])
            ),
            revoked_at=(
                None
                if row["revoked_at"] is None
                else datetime.fromisoformat(row["revoked_at"])
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
