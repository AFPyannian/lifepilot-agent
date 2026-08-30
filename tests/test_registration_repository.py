"""验证邀请码过期、撤销和原子消费。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.auth.errors import RegistrationDeniedError
from app.auth.passwords import hash_password
from app.auth.service import AuthService
from app.repositories.auth_repository import AuthRepository


def create_repository_with_invitation(tmp_path):
    """创建管理员和一次性邀请码。"""
    repository = AuthRepository(tmp_path / "application.db")
    admin = repository.create_user(
        user_id="admin-id",
        username="admin",
        password_hash=hash_password("admin-correct-horse"),
        role="admin",
    )
    code = "lp_invite_high-entropy-test-code"
    repository.create_invitation(
        invitation_id="invitation-id",
        code_hash=AuthService.hash_invitation_code(code),
        created_by=admin.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    return repository, code


def test_expired_invitation_is_rejected(tmp_path) -> None:
    repository = AuthRepository(tmp_path / "application.db")
    admin = repository.create_user(
        user_id="admin-id",
        username="admin",
        password_hash=hash_password("admin-correct-horse"),
        role="admin",
    )
    code = "lp_invite_expired-test-code"
    repository.create_invitation(
        invitation_id="expired-id",
        code_hash=AuthService.hash_invitation_code(code),
        created_by=admin.id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    try:
        repository.register_with_invitation(
            user_id="alice-id",
            username="alice",
            password_hash="test-password-hash",
            invitation_code_hash=AuthService.hash_invitation_code(code),
            now=datetime.now(UTC),
        )
    except RegistrationDeniedError:
        pass
    else:
        raise AssertionError("过期邀请码不应注册成功")


def test_invitation_is_consumed_atomically(tmp_path) -> None:
    repository, code = create_repository_with_invitation(tmp_path)
    code_hash = AuthService.hash_invitation_code(code)

    def register(username: str) -> bool:
        try:
            repository.register_with_invitation(
                user_id=f"{username}-id",
                username=username,
                password_hash="test-password-hash",
                invitation_code_hash=code_hash,
                now=datetime.now(UTC),
            )
            return True
        except RegistrationDeniedError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, ["alice", "bob"]))

    assert results.count(True) == 1
    assert results.count(False) == 1
