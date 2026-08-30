"""执行可重试且幂等的知识文档索引任务。"""

from typing import Any

from app.config import get_settings
from app.database import Database
from app.knowledge.production_service import ProductionKnowledgeService
from app.tasks.celery_app import celery_app

settings = get_settings()


@celery_app.task(
    bind=True,
    autoretry_for=(OSError, ConnectionError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=settings.knowledge_task_max_retries,
    acks_late=True,
    reject_on_worker_lost=True,
    name="lifepilot.knowledge.ingest",
)
def ingest_knowledge_document(self: Any, document_id: str) -> dict[str, object]:
    """下载并重建文档向量；重复执行会覆盖同一文档的旧片段。"""
    settings = get_settings()
    database = Database(settings)
    try:
        service = ProductionKnowledgeService(database, settings)
        result = service.ingest_document(document_id)
        return {
            "filename": result.source_name,
            "chunk_count": result.chunk_count,
            "status": result.status,
        }
    finally:
        database.close()
