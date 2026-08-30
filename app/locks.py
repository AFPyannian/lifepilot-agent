"""提供本地和 PostgreSQL 会话级互斥锁。"""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.database import Database
from app.exceptions import ExecutionBusyError


@contextmanager
def execution_scope(
    lock_manager: object, user_id: str, resource_id: str
) -> Iterator[None]:
    """统一适配新锁管理器和测试中注入的传统 ``Lock``。"""
    if isinstance(lock_manager, (LocalExecutionLock, PostgresExecutionLock)):
        with lock_manager.acquire(user_id, resource_id):
            yield
        return

    enter = getattr(lock_manager, "__enter__", None)
    exit_method = getattr(lock_manager, "__exit__", None)
    if enter is None or exit_method is None:
        raise TypeError("不支持的执行锁")
    with lock_manager:  # type: ignore[attr-defined]
        yield


class LocalExecutionLock:
    """兼容单实例开发模式的细粒度进程锁。"""

    def __init__(self) -> None:
        self._guard = Lock()
        self._locks: dict[str, tuple[Lock, int]] = {}

    @contextmanager
    def acquire(self, user_id: str, thread_id: str) -> Iterator[None]:
        key = f"{user_id}:{thread_id}"
        with self._guard:
            lock, references = self._locks.get(key, (Lock(), 0))
            self._locks[key] = (lock, references + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                current_lock, references = self._locks[key]
                if references == 1:
                    self._locks.pop(key)
                else:
                    self._locks[key] = (current_lock, references - 1)


class PostgresExecutionLock:
    """使用事务级 advisory lock 串行化同一用户会话。"""

    def __init__(self, database: Database, wait_seconds: float) -> None:
        self._database = database
        self._wait_seconds = wait_seconds

    @staticmethod
    def _key(user_id: str, thread_id: str) -> int:
        digest = hashlib.blake2b(
            f"{user_id}\0{thread_id}".encode(), digest_size=8
        ).digest()
        return int.from_bytes(digest, byteorder="big", signed=True)

    @contextmanager
    def acquire(self, user_id: str, thread_id: str) -> Iterator[None]:
        lock_key = self._key(user_id, thread_id)
        with self._database.session() as session:
            try:
                session.execute(
                    text("SELECT set_config('lock_timeout', :timeout, true)"),
                    {"timeout": f"{int(self._wait_seconds * 1000)}ms"},
                )
                session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            except OperationalError as error:
                raise ExecutionBusyError(
                    "PostgreSQL advisory lock timed out"
                ) from error
            yield
