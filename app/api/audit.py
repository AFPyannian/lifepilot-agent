"""提供 API 路由使用的安全审计辅助函数。"""

import logging

from fastapi import Request

logger = logging.getLogger("lifepilot.api.audit")


def record_audit_event(
    request: Request,
    *,
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str,
) -> None:
    """尽力写入审计事件，失败时不影响主业务响应。"""
    repository = getattr(request.app.state, "audit_repository", None)
    if repository is None:
        return

    request_id = getattr(request.state, "request_id", "unknown")

    try:
        repository.record(
            request_id=request_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
        )
    except Exception:
        logger.exception(
            "Audit event persistence failed request_id=%s action=%s",
            request_id,
            action,
        )
