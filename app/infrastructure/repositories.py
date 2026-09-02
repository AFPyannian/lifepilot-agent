"""集中创建 local 与 production 仓储实现。"""

from dataclasses import dataclass

from app.config import Settings
from app.database import Database
from app.repositories.postgres import (
    PostgresAuditRepository,
    PostgresAuthRepository,
    PostgresConversationRepository,
    PostgresEntitlementRepository,
    PostgresNoteRepository,
    PostgresProviderCredentialRepository,
    PostgresQuotaRepository,
    PostgresTodoRepository,
    PostgresUsageRepository,
    PostgresUserMemoryRepository,
)
from app.repositories.protocols import (
    AuditRepositoryProtocol,
    AuthRepositoryProtocol,
    ConversationRepositoryProtocol,
    EntitlementRepositoryProtocol,
    NoteRepositoryProtocol,
    ProviderCredentialRepositoryProtocol,
    QuotaRepositoryProtocol,
    TodoRepositoryProtocol,
    UsageRepositoryProtocol,
    UserMemoryRepositoryProtocol,
)
from app.repositories.sqlite import (
    SQLiteAuditRepository,
    SQLiteAuthRepository,
    SQLiteConversationRepository,
    SQLiteEntitlementRepository,
    SQLiteNoteRepository,
    SQLiteProviderCredentialRepository,
    SQLiteQuotaRepository,
    SQLiteTodoRepository,
    SQLiteUsageRepository,
    SQLiteUserMemoryRepository,
)


@dataclass(frozen=True)
class RepositoryBundle:
    """保存一次应用生命周期中共享的仓储实例。"""

    database: Database | None
    auth: AuthRepositoryProtocol
    audit: AuditRepositoryProtocol
    conversation: ConversationRepositoryProtocol
    entitlement: EntitlementRepositoryProtocol
    note: NoteRepositoryProtocol
    provider_credential: ProviderCredentialRepositoryProtocol
    quota: QuotaRepositoryProtocol
    todo: TodoRepositoryProtocol
    usage: UsageRepositoryProtocol
    user_memory: UserMemoryRepositoryProtocol


def create_repositories(settings: Settings) -> RepositoryBundle:
    """根据基础设施模式创建完整且类型一致的仓储集合。"""
    if settings.infrastructure_mode == "production":
        database = Database(settings)
        try:
            return RepositoryBundle(
                database=database,
                auth=PostgresAuthRepository(database),
                audit=PostgresAuditRepository(database),
                conversation=PostgresConversationRepository(database),
                entitlement=PostgresEntitlementRepository(database),
                note=PostgresNoteRepository(database),
                provider_credential=PostgresProviderCredentialRepository(database),
                quota=PostgresQuotaRepository(database),
                todo=PostgresTodoRepository(database),
                usage=PostgresUsageRepository(database),
                user_memory=PostgresUserMemoryRepository(database),
            )
        except Exception:
            database.close()
            raise

    database_path = settings.app_database_path
    return RepositoryBundle(
        database=None,
        auth=SQLiteAuthRepository(database_path),
        audit=SQLiteAuditRepository(database_path),
        conversation=SQLiteConversationRepository(database_path),
        entitlement=SQLiteEntitlementRepository(database_path),
        note=SQLiteNoteRepository(database_path),
        provider_credential=SQLiteProviderCredentialRepository(database_path),
        quota=SQLiteQuotaRepository(database_path),
        todo=SQLiteTodoRepository(database_path),
        usage=SQLiteUsageRepository(database_path),
        user_memory=SQLiteUserMemoryRepository(database_path),
    )
