"""提供公开的服务存活和生产依赖就绪检查接口。"""

import logging
from typing import Any

from fastapi import APIRouter, Request, Response, status
from psycopg import connect
from starlette.concurrency import run_in_threadpool

from app.api.schemas import HealthResponse

router = APIRouter()
logger = logging.getLogger("lifepilot.health")


def _ping_checkpoint(database_url: str) -> None:
    """建立独立短连接，确认 Checkpoint 数据库可查询。"""
    with (
        connect(database_url, connect_timeout=3) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT 1")


def _not_ready(response: Response) -> HealthResponse:
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="not_ready", service="lifepilot-agent")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="检查 LifePilot 服务状态",
)
def health_check() -> HealthResponse:
    """返回 LifePilot 进程存活状态。"""
    return HealthResponse(
        status="ok",
        service="lifepilot-agent",
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="检查 LifePilot Agent 就绪状态",
)
async def readiness_check(
    request: Request,
    response: Response,
) -> HealthResponse:
    """确认 Agent 图及生产共享依赖仍可用。"""
    graph = getattr(request.app.state, "agent_graph", None)

    if graph is None:
        return _not_ready(response)

    database = getattr(request.app.state, "database", None)
    if database is None:
        return HealthResponse(status="ready", service="lifepilot-agent")

    try:
        await run_in_threadpool(database.ping)

        limiter = getattr(request.app.state, "api_rate_limiter", None)
        if limiter is not None:
            await limiter.ping()

        knowledge_service = getattr(request.app.state, "knowledge_service", None)
        if knowledge_service is not None:
            await run_in_threadpool(knowledge_service.ping)

        settings: Any = request.app.state.settings
        checkpoint_url = settings.checkpoint_database_url
        if checkpoint_url is None:
            return _not_ready(response)
        await run_in_threadpool(
            _ping_checkpoint,
            checkpoint_url.get_secret_value(),
        )
    except Exception as error:
        logger.warning(
            "Readiness dependency check failed error_type=%s",
            type(error).__name__,
        )
        return _not_ready(response)

    return HealthResponse(
        status="ready",
        service="lifepilot-agent",
    )
