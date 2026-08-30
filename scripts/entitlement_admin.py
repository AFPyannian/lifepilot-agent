"""通过命令行查询、发放和撤销 LifePilot 能力授权。"""

import argparse
from datetime import UTC, datetime, timedelta

from app.access.models import Capability
from app.access.service import EntitlementService
from app.config import get_settings
from app.repositories.auth_repository import AuthRepository
from app.repositories.entitlement_repository import EntitlementRepository


def _require_user(repository: AuthRepository, username: str):
    user = repository.get_user_by_username(username)
    if user is None:
        raise ValueError(f"用户不存在：{username}")
    return user


def main() -> None:
    """解析本地管理员命令并更新授权记录。"""
    parser = argparse.ArgumentParser(description="管理 LifePilot 用户能力授权")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--username", required=True)

    grant_parser = subparsers.add_parser("grant")
    grant_parser.add_argument("--username", required=True)
    grant_parser.add_argument("--granted-by", required=True)
    grant_parser.add_argument(
        "--capability",
        choices=[capability.value for capability in Capability],
        required=True,
    )
    grant_parser.add_argument("--expires-in-days", type=int)

    revoke_parser = subparsers.add_parser("revoke")
    revoke_parser.add_argument("--entitlement-id", required=True)

    args = parser.parse_args()
    settings = get_settings()
    auth_repository = AuthRepository(settings.app_database_path)
    service = EntitlementService(EntitlementRepository(settings.app_database_path))

    try:
        if args.command == "list":
            user = _require_user(auth_repository, args.username)
            records = service.list_for_user(user.id)
            if not records:
                print("该用户没有授权记录。")
            for record in records:
                print(
                    f"{record.id}  {record.capability.value}  "
                    f"{record.status.value}  {record.source.value}  "
                    f"expires={record.expires_at or 'never'}"
                )
        elif args.command == "grant":
            user = _require_user(auth_repository, args.username)
            admin = _require_user(auth_repository, args.granted_by)
            if admin.role != "admin" or admin.status != "active":
                raise ValueError("授权人必须是启用状态的管理员。")
            if args.expires_in_days is not None and args.expires_in_days <= 0:
                raise ValueError("有效天数必须大于 0。")
            expires_at = (
                None
                if args.expires_in_days is None
                else datetime.now(UTC) + timedelta(days=args.expires_in_days)
            )
            record = service.grant_admin(
                user_id=user.id,
                created_by=admin.id,
                capability=Capability(args.capability),
                expires_at=expires_at,
            )
            print(f"授权创建成功：{record.id}")
        elif not service.revoke(args.entitlement_id):
            raise ValueError("有效授权不存在或已经撤销。")
        else:
            print(f"授权已撤销：{args.entitlement_id}")
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
