"""配置 Celery Worker 和知识处理队列。"""

from celery import Celery  # type: ignore[import-untyped]

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "lifepilot",
    broker=(
        settings.celery_broker_url.get_secret_value()
        if settings.celery_broker_url is not None
        else None
    ),
    backend=(
        settings.celery_result_backend.get_secret_value()
        if settings.celery_result_backend is not None
        else None
    ),
    include=["app.tasks.knowledge"],
)
celery_app.conf.update(
    task_default_queue=settings.knowledge_worker_queue,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
