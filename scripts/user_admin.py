"""通过命令行创建和管理 LifePilot 用户。"""

import argparse
import getpass
from uuid import uuid4

from app.auth.passwords import hash_password
from app.config import get_settings
from app.repositories.auth_repository import AuthRepository


def _read_new_password() -> str:
    password = getpass.getpass("请输入新密码（至少12个字符）：")
    confirmation = getpass.getpass("请再次输入新密码：")
    if password != confirmation:
        raise ValueError("两次输入的密码不一致。")
    return password


def _create_user(
    repository: AuthRepository,
    username: str,
    role: str,
) -> None:
    user = repository.create_user(
        user_id=str(uuid4()),
        username=username,
        password_hash=hash_password(_read_new_password()),
        role=role,
    )
    print(f"用户创建成功：{user.username}（{user.id}，{user.role}）")


def _set_status(
    repository: AuthRepository,
    username: str,
    status: str,
) -> None:
    user = repository.get_user_by_username(username)
    if user is None:
        raise ValueError("用户不存在。")
    if not repository.set_user_status(user.id, status):
        raise RuntimeError("用户状态更新失败。")
    print(f"用户状态已更新：{user.username} -> {status}")


def _reset_password(
    repository: AuthRepository,
    username: str,
) -> None:
    user = repository.get_user_by_username(username)
    if user is None:
        raise ValueError("用户不存在。")
    repository.update_password_hash(
        user.id,
        hash_password(_read_new_password()),
    )
    repository.revoke_all_sessions(user.id)
    print(f"密码已重置并撤销全部 Session：{user.username}")


def main() -> None:
    """解析管理员命令并更新账号数据库。"""
    parser = argparse.ArgumentParser(description="管理 LifePilot 本地用户")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--username", required=True)
    create_parser.add_argument(
        "--role",
        choices=["admin", "user"],
        default="user",
    )

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--username", required=True)
    status_parser.add_argument(
        "--status",
        choices=["active", "disabled"],
        required=True,
    )

    reset_parser = subparsers.add_parser("reset-password")
    reset_parser.add_argument("--username", required=True)

    args = parser.parse_args()
    repository = AuthRepository(get_settings().app_database_path)

    try:
        if args.command == "create":
            _create_user(repository, args.username, args.role)
        elif args.command == "status":
            _set_status(repository, args.username, args.status)
        else:
            _reset_password(repository, args.username)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
