from app.config import Settings
from app.knowledge.service import (
    IngestionResult,
    KnowledgeBaseService,
    KnowledgeSource,
)
from app.knowledge.vector_store import (
    create_knowledge_vector_store,
)


def create_knowledge_base_service(
    settings: Settings,
) -> KnowledgeBaseService:
    """根据统一配置创建知识库服务。"""
    return KnowledgeBaseService(
        source_directory=settings.knowledge_source_directory,
        vector_store_factory=lambda: create_knowledge_vector_store(
            settings
        ),
        chunk_size=settings.knowledge_chunk_size,
        chunk_overlap=settings.knowledge_chunk_overlap,
        retrieval_k=settings.knowledge_retrieval_k,
        max_file_bytes=settings.knowledge_max_file_bytes,
    )


__all__ = [
    "IngestionResult",
    "KnowledgeBaseService",
    "KnowledgeSource",
    "create_knowledge_base_service",
]