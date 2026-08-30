"""验证用户模型凭据的加密、生命周期和接口边界。"""

import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.server import create_app
from app.credentials.crypto import CredentialCipher
from app.credentials.errors import (
    CredentialDecryptionError,
    CredentialValidationError,
)
from app.credentials.service import ProviderCredentialService
from app.repositories.audit_repository import AuditRepository
from app.repositories.auth_repository import AuthRepository
from app.repositories.provider_credential_repository import (
    ProviderCredentialRepository,
)
from scripts import rewrap_provider_credentials as rewrap_module
from tests.helpers import TEST_ACCESS_TOKEN, FakeAuthService

TEST_KEY = "sk-test-never-store-plaintext-7x9k"


class AcceptValidator:
    """提供不访问外部服务的凭据验证器。"""

    def validate(self, secret: SecretStr) -> None:
        assert secret.get_secret_value()


class RejectValidator:
    """模拟供应商拒绝凭据。"""

    def validate(self, secret: SecretStr) -> None:
        del secret
        raise CredentialValidationError("Credential rejected.")


class FakeGraph:
    """提供模型凭据 API 测试所需的最小图。"""

    checkpointer = None


def create_user(database_path, user_id: str, username: str) -> None:
    repository = AuthRepository(database_path)
    repository.create_user(
        user_id=user_id,
        username=username,
        password_hash="test-password-hash",
        role="user",
    )


def create_service(database_path, validator=None) -> ProviderCredentialService:
    return ProviderCredentialService(
        repository=ProviderCredentialRepository(database_path),
        cipher=CredentialCipher(
            keyring={"v1": b"a" * 32},
            active_key_version="v1",
        ),
        validator=validator or AcceptValidator(),
    )


def test_cipher_rejects_tampering_and_cross_user_swap() -> None:
    cipher = CredentialCipher(
        keyring={"v1": b"a" * 32},
        active_key_version="v1",
    )
    encrypted = cipher.encrypt(
        secret=SecretStr(TEST_KEY),
        credential_id="credential-1",
        user_id="alice",
        provider="deepseek",
    )

    assert TEST_KEY not in encrypted.ciphertext
    assert (
        cipher.decrypt(
            ciphertext=encrypted.ciphertext,
            key_version=encrypted.key_version,
            credential_id="credential-1",
            user_id="alice",
            provider="deepseek",
        ).get_secret_value()
        == TEST_KEY
    )

    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt(
            ciphertext=encrypted.ciphertext,
            key_version=encrypted.key_version,
            credential_id="credential-1",
            user_id="bob",
            provider="deepseek",
        )


def test_credentials_are_encrypted_isolated_rotated_and_revoked(tmp_path) -> None:
    database_path = tmp_path / "application.db"
    create_user(database_path, "alice", "alice")
    create_user(database_path, "bob", "bob")
    service = create_service(database_path)

    first = service.save_or_rotate(user_id="alice", api_key=SecretStr(TEST_KEY))
    service.save_or_rotate(
        user_id="bob",
        api_key=SecretStr("sk-bob-private-key-1234"),
    )

    assert first.masked_suffix == "7x9k"
    assert service.resolve_active(user_id="alice").secret.get_secret_value() == TEST_KEY
    assert (
        service.resolve_active(user_id="bob").secret.get_secret_value()
        == "sk-bob-private-key-1234"
    )
    assert TEST_KEY.encode() not in database_path.read_bytes()

    service.save_or_rotate(
        user_id="alice",
        api_key=SecretStr("sk-alice-rotated-key-8888"),
    )
    assert (
        service.resolve_active(user_id="alice").secret.get_secret_value()
        == "sk-alice-rotated-key-8888"
    )

    assert service.revoke(user_id="alice") is True
    record = ProviderCredentialRepository(database_path).get(
        user_id="alice",
        provider="deepseek",
    )
    assert record is not None
    assert record.status == "revoked"
    assert record.encrypted_secret is None
    assert (
        service.resolve_active(user_id="bob").secret.get_secret_value().endswith("1234")
    )


def test_invalid_key_is_not_stored(tmp_path) -> None:
    database_path = tmp_path / "application.db"
    create_user(database_path, "alice", "alice")
    service = create_service(database_path, RejectValidator())

    with pytest.raises(CredentialValidationError):
        service.save_or_rotate(user_id="alice", api_key=SecretStr(TEST_KEY))

    assert (
        ProviderCredentialRepository(database_path).get(
            user_id="alice",
            provider="deepseek",
        )
        is None
    )
    assert TEST_KEY.encode() not in database_path.read_bytes()


def test_credential_api_never_returns_or_audits_raw_key(tmp_path) -> None:
    database_path = tmp_path / "application.db"
    create_user(database_path, "owner-1", "alice")
    service = create_service(database_path)
    settings = SimpleNamespace(
        api_rate_limit_enabled=False,
        agent_recursion_limit=25,
        app_environment="test",
        byok_enabled=True,
        platform_model_enabled=True,
        default_model_mode="PLATFORM",
    )
    app = create_app(
        agent_graph=FakeGraph(),
        settings=settings,
        auth_service=FakeAuthService(),
        audit_repository=AuditRepository(database_path),
        provider_credential_service=service,
    )
    headers = {"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"}

    with TestClient(app) as client:
        response = client.put(
            "/api/v1/model/credentials/deepseek",
            headers=headers,
            json={"api_key": TEST_KEY},
        )
        metadata = response.json()

        assert response.status_code == 200
        assert metadata["masked_key"] == "••••7x9k"
        assert TEST_KEY not in response.text
        assert "encrypted_secret" not in metadata
        assert "fingerprint" not in metadata

        access = client.get("/api/v1/model/access", headers=headers)
        assert access.json()["byok_configured"] is True

        revoke = client.post(
            "/api/v1/model/credentials/deepseek/revoke",
            headers=headers,
        )
        assert revoke.status_code == 204

    assert TEST_KEY.encode() not in database_path.read_bytes()

    with closing(sqlite3.connect(database_path)) as connection:
        audit_text = " ".join(
            str(value)
            for row in connection.execute("SELECT * FROM audit_events").fetchall()
            for value in row
        )

    assert TEST_KEY not in audit_text


def test_master_key_rotation_rewraps_existing_ciphertext(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "application.db"
    create_user(database_path, "alice", "alice")
    service = create_service(database_path)
    service.save_or_rotate(user_id="alice", api_key=SecretStr(TEST_KEY))

    keyring = {"v1": b"a" * 32, "v2": b"b" * 32}
    fake_settings = SimpleNamespace(
        app_database_path=database_path,
        provider_credential_active_key_version="v2",
        provider_credential_keyring=lambda: keyring,
    )
    monkeypatch.setattr(rewrap_module, "get_settings", lambda: fake_settings)

    assert rewrap_module.rewrap_credentials("v1") == 1

    record = ProviderCredentialRepository(database_path).get(
        user_id="alice",
        provider="deepseek",
    )
    assert record is not None
    assert record.encryption_key_version == "v2"
    assert record.encrypted_secret is not None
    assert (
        CredentialCipher(keyring=keyring, active_key_version="v2")
        .decrypt(
            ciphertext=record.encrypted_secret,
            key_version="v2",
            credential_id=record.id,
            user_id=record.user_id,
            provider=record.provider,
        )
        .get_secret_value()
        == TEST_KEY
    )
