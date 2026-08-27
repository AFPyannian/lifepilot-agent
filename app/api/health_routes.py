"""提供公开的服务存活和就绪检查接口。"""

from fastapi import APIRouter, Request, Response, status

from app.api.schemas import HealthResponse

router = APIRouter()


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
def readiness_check(
    request: Request,
    response: Response,
) -> HealthResponse:
    """根据 Agent 图是否完成初始化返回就绪状态。"""
    graph = getattr(request.app.state, "agent_graph", None)

    if graph is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="not_ready",
            service="lifepilot-agent",
        )

    return HealthResponse(
        status="ready",
        service="lifepilot-agent",
    )
