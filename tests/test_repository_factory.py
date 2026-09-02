"""验证 local/production 仓储装配遵循相同契约。"""

from pathlib import Path

import pytest

from app.config import Settings
from app.infrastructure import create_repositories
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


def test_local_repository_bundle_satisfies_shared_contracts(tmp_path: Path) -> None:
    repositories = create_repositories(
        Settings(
            _env_file=None,
            deepseek_api_key="test-key",
            app_database_path=tmp_path / "lifepilot.db",
        )
    )

    assert repositories.database is None
    assert isinstance(repositories.audit, AuditRepositoryProtocol)
    assert isinstance(repositories.auth, AuthRepositoryProtocol)
    assert isinstance(repositories.conversation, ConversationRepositoryProtocol)
    assert isinstance(repositories.entitlement, EntitlementRepositoryProtocol)
    assert isinstance(repositories.note, NoteRepositoryProtocol)
    assert isinstance(
        repositories.provider_credential,
        ProviderCredentialRepositoryProtocol,
    )
    assert isinstance(repositories.quota, QuotaRepositoryProtocol)
    assert isinstance(repositories.todo, TodoRepositoryProtocol)
    assert isinstance(repositories.usage, UsageRepositoryProtocol)
    assert isinstance(repositories.user_memory, UserMemoryRepositoryProtocol)


@pytest.mark.parametrize(
    ("implementation", "contract"),
    [
        (PostgresAuditRepository, AuditRepositoryProtocol),
        (PostgresAuthRepository, AuthRepositoryProtocol),
        (PostgresConversationRepository, ConversationRepositoryProtocol),
        (PostgresEntitlementRepository, EntitlementRepositoryProtocol),
        (PostgresNoteRepository, NoteRepositoryProtocol),
        (
            PostgresProviderCredentialRepository,
            ProviderCredentialRepositoryProtocol,
        ),
        (PostgresQuotaRepository, QuotaRepositoryProtocol),
        (PostgresTodoRepository, TodoRepositoryProtocol),
        (PostgresUsageRepository, UsageRepositoryProtocol),
        (PostgresUserMemoryRepository, UserMemoryRepositoryProtocol),
    ],
)
def test_postgres_repository_classes_satisfy_shared_contracts(
    implementation: type[object], contract: type[object]
) -> None:
    repository = object.__new__(implementation)
    assert isinstance(repository, contract)
