"""验证月度配额配置、原子请求预占和 Token 结算。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

from app.auth.passwords import hash_password
from app.exceptions import QuotaExceededError
from app.quota.service import QuotaService
from app.repositories.auth_repository import AuthRepository
from app.repositories.quota_repository import QuotaRepository


def _repository(tmp_path: Path) -> QuotaRepository:
    database_path = tmp_path / "quota.db"
    auth = AuthRepository(database_path)
    auth.create_user(
        user_id="user-id",
        username="alice",
        password_hash=hash_password("correct-horse-battery"),
        role="user",
    )
    return QuotaRepository(database_path)


def test_quota_reservation_and_token_limit(tmp_path) -> None:
    repository = _repository(tmp_path)
    period = date(2026, 8, 1)
    repository.set_quota(
        user_id="user-id",
        monthly_request_limit=3,
        monthly_token_limit=10,
        updated_by=None,
    )

    assert repository.reserve_model_request("user-id", period)
    repository.add_tokens("user-id", period, 10)
    assert not repository.reserve_model_request("user-id", period)

    status = repository.get_status("user-id", period)
    assert status.request_count == 1
    assert status.token_count == 10


def test_quota_request_reservation_is_atomic(tmp_path) -> None:
    repository = _repository(tmp_path)
    period = date(2026, 8, 1)
    repository.set_quota(
        user_id="user-id",
        monthly_request_limit=1,
        monthly_token_limit=None,
        updated_by=None,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: repository.reserve_model_request("user-id", period),
                range(2),
            )
        )

    assert sorted(results) == [False, True]


def test_quota_service_raises_safe_error(tmp_path, monkeypatch) -> None:
    repository = _repository(tmp_path)
    service = QuotaService(repository)
    period = date(2026, 8, 1)
    monkeypatch.setattr(service, "current_period", lambda: period)
    repository.set_quota(
        user_id="user-id",
        monthly_request_limit=1,
        monthly_token_limit=None,
        updated_by=None,
    )

    service.reserve_model_request("user-id")
    with pytest.raises(QuotaExceededError, match="Monthly model quota exceeded"):
        service.reserve_model_request("user-id")
