"""创建并管理生产 PostgreSQL 连接池。"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


class Database:
    """封装 SQLAlchemy Engine 和短事务 Session。"""

    def __init__(self, settings: Settings) -> None:
        if settings.database_url is None:
            raise ValueError("DATABASE_URL 尚未配置")

        self.engine: Engine = create_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_recycle=settings.database_pool_recycle_seconds,
        )
        self._session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        """提供提交成功、异常回滚的短事务 Session。"""
        with self._session_factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def close(self) -> None:
        """释放连接池持有的连接。"""
        self.engine.dispose()

    def ping(self) -> None:
        """验证业务数据库连接可用。"""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
