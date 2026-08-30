"""验证阶段四无需外部服务即可检查的生产化边界。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.locks import LocalExecutionLock, PostgresExecutionLock, execution_scope


def test_production_settings_require_all_shared_services() -> None:
    with pytest.raises(ValidationError, match="生产基础设施配置缺失"):
        Settings(
            deepseek_api_key=SecretStr("test-key"),
            infrastructure_mode="production",
        )


def test_advisory_lock_key_is_stable_and_scoped() -> None:
    first = PostgresExecutionLock._key("user-1", "thread-1")
    assert first == PostgresExecutionLock._key("user-1", "thread-1")
    assert first != PostgresExecutionLock._key("user-2", "thread-1")
    assert first != PostgresExecutionLock._key("user-1", "thread-2")


def test_local_execution_lock_does_not_globally_block_other_threads() -> None:
    manager = LocalExecutionLock()
    first_entered = Event()
    second_entered = Event()
    release_first = Event()

    def hold_first() -> None:
        with execution_scope(manager, "user-1", "thread-1"):
            first_entered.set()
            release_first.wait(timeout=2)

    def enter_second() -> None:
        first_entered.wait(timeout=2)
        with execution_scope(manager, "user-1", "thread-2"):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(hold_first)
        second = executor.submit(enter_second)
        assert second_entered.wait(timeout=1)
        release_first.set()
        first.result(timeout=2)
        second.result(timeout=2)
