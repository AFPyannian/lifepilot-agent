"""验证用户、密码和 Session 持久化安全。"""

import sqlite3
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest

from app.auth.passwords import hash_password, verify_password
from app.repositories.auth_repository import AuthRepository


def create_user(repository: AuthRepository, username: str = "alice"):
    """创建使用固定测试密码的用户。"""
    password = "correct-horse-battery"
    return repository.create_user(
        user_id=str(uuid4()),
        username=username,
        password_hash=hash_password(password),
        role="user",
    )


def test_password_is_argon2id_hash() -> None:
    password = "correct-horse-battery"
    password_hash = hash_password(password)

    assert password not in password_hash
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, password)
    assert not verify_password(password_hash, "wrong-password")


def test_username_is_unique_case_insensitively(tmp_path) -> None:
    repository = AuthRepository(tmp_path / "application.db")
    create_user(repository, "Alice")

    with pytest.raises(ValueError, match="用户名已经存在"):
        create_user(repository, "alice")


def test_database_only_stores_session_token_hash(tmp_path) -> None:
    database_path = tmp_path / "application.db"
    repository = AuthRepository(database_path)
    user = create_user(repository)
    raw_token = "high-entropy-session-token"
    token_hash = sha256(raw_token.encode()).hexdigest()

    repository.create_session(
        session_id="session-1",
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    with sqlite3.connect(database_path) as connection:
        stored_token = connection.execute(
            "SELECT token_hash FROM auth_sessions"
        ).fetchone()[0]

    assert stored_token == token_hash
    assert stored_token != raw_token


def test_disabled_user_loses_all_sessions(tmp_path) -> None:
    repository = AuthRepository(tmp_path / "application.db")
    user = create_user(repository)
    raw_token = "session-token"
    token_hash = sha256(raw_token.encode()).hexdigest()
    now = datetime.now(UTC)

    repository.create_session(
        session_id="session-1",
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + timedelta(hours=1),
    )
    assert repository.find_principal_by_token_hash(token_hash, now) is not None

    repository.set_user_status(user.id, "disabled")

    assert repository.find_principal_by_token_hash(token_hash, now) is None


def test_expired_session_is_rejected(tmp_path) -> None:
    repository = AuthRepository(tmp_path / "application.db")
    user = create_user(repository)
    token_hash = sha256(b"expired-session").hexdigest()
    now = datetime.now(UTC)

    repository.create_session(
        session_id="expired-session",
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now - timedelta(seconds=1),
    )

    assert repository.find_principal_by_token_hash(token_hash, now) is None
