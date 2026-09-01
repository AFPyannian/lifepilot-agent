"""使用显式启用的真实服务验证阶段四生产基础设施。"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.config import Settings
from app.database import Database
from app.redis_rate_limit import RedisApiRateLimiter
from app.repositories.postgres import PostgresAuthRepository, PostgresQuotaRepository
from app.storage import S3ObjectStorage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_PRODUCTION_INTEGRATION_TESTS", "").lower() != "true",
        reason="需要显式启用阶段四真实基础设施测试",
    ),
]


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"缺少集成测试环境变量 {name}")
    return value


@pytest.fixture(scope="module")
def production_settings() -> Settings:
    return Settings(
        _env_file=None,
        deepseek_api_key="integration-test-not-used",
        byok_enabled=False,
        platform_model_enabled=True,
        infrastructure_mode="production",
        database_url=_required("DATABASE_URL"),
        checkpoint_database_url=_required("CHECKPOINT_DATABASE_URL"),
        redis_url=_required("REDIS_URL"),
        celery_broker_url=_required("CELERY_BROKER_URL"),
        celery_result_backend=_required("CELERY_RESULT_BACKEND"),
        object_storage_endpoint_url=_required("OBJECT_STORAGE_ENDPOINT_URL"),
        object_storage_access_key=_required("OBJECT_STORAGE_ACCESS_KEY"),
        object_storage_secret_key=_required("OBJECT_STORAGE_SECRET_KEY"),
        object_storage_secure=False,
        object_storage_sse="none",
        app_environment="test",
    )


def test_postgres_pgvector_and_checkpoint_schema(
    production_settings: Settings,
) -> None:
    database = Database(production_settings)
    try:
        database.ping()
        with database.engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
                )
            )
            for table_name in (
                "users",
                "knowledge_chunks",
                "user_quotas",
                "quota_usage",
                "checkpoints",
            ):
                assert connection.scalar(
                    text("SELECT to_regclass(:name) IS NOT NULL"),
                    {"name": f"public.{table_name}"},
                )
    finally:
        database.close()


def test_postgres_quota_reservation_is_cross_connection_atomic(
    production_settings: Settings,
) -> None:
    database = Database(production_settings)
    user_id = f"integration-{uuid4().hex}"
    try:
        PostgresAuthRepository(database).create_user(
            user_id=user_id,
            username=user_id,
            password_hash="integration-test-only",
            role="user",
        )
        quota = PostgresQuotaRepository(database)
        quota.set_quota(
            user_id=user_id,
            monthly_request_limit=1,
            monthly_token_limit=None,
            updated_by=None,
        )
        period = date.today().replace(day=1)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: quota.reserve_model_request(user_id, period),
                    range(2),
                )
            )
        assert sorted(results) == [False, True]
    finally:
        with database.session() as session:
            session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        database.close()


def test_redis_shared_sliding_window(production_settings: Settings) -> None:
    async def exercise() -> None:
        assert production_settings.redis_url is not None
        limiter = RedisApiRateLimiter(
            production_settings.redis_url.get_secret_value(),
            f"lifepilot:integration:{uuid4().hex}",
        )
        try:
            await limiter.ping()
            assert await limiter.check("user", 2, 10) is None
            assert await limiter.check("user", 2, 10) is None
            assert await limiter.check("user", 2, 10) is not None
        finally:
            await limiter.close()

    asyncio.run(exercise())


def test_minio_private_bucket_round_trip(
    production_settings: Settings,
    tmp_path: Path,
) -> None:
    storage = S3ObjectStorage(production_settings)
    object_key = f"integration/{uuid4().hex}.txt"
    destination = tmp_path / "downloaded.txt"
    try:
        storage.ping()
        storage.upload(BytesIO(b"lifepilot-phase4"), object_key, "text/plain")
        storage.download(object_key, destination)
        assert destination.read_bytes() == b"lifepilot-phase4"
    finally:
        storage.delete(object_key)
