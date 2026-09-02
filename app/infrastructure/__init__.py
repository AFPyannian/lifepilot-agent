"""按运行模式装配外部基础设施。"""

from app.infrastructure.repositories import RepositoryBundle, create_repositories

__all__ = ["RepositoryBundle", "create_repositories"]
