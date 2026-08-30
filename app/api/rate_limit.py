"""提供进程内滑动窗口 API 限流。"""

import asyncio
import hashlib
import json
import math
import time
from collections import defaultdict, deque

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SlidingWindowRateLimitMiddleware:
    """按照 Session Token 摘要或客户端地址限制业务接口请求。"""

    def __init__(self, app: ASGIApp) -> None:
        """保存下游应用并初始化进程内请求窗口。"""
        self.app = app
        self._requests: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """在业务请求进入路由前执行滑动窗口限流。"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        if not path.startswith("/api/v1/"):
            await self.app(scope, receive, send)
            return

        if path in {"/api/v1/health", "/api/v1/ready"}:
            await self.app(scope, receive, send)
            return

        application = scope.get("app")
        settings = getattr(getattr(application, "state", None), "settings", None)

        if not getattr(settings, "api_rate_limit_enabled", False):
            await self.app(scope, receive, send)
            return

        request_limit = getattr(settings, "api_rate_limit_requests", 60)
        window_seconds = getattr(settings, "api_rate_limit_window_seconds", 60)

        identifier = self._get_identifier(scope)
        now = time.monotonic()
        window_start = now - window_seconds
        retry_after: int | None = None

        shared_limiter = getattr(
            getattr(application, "state", None), "api_rate_limiter", None
        )
        if shared_limiter is not None:
            retry_after = await shared_limiter.check(
                identifier, request_limit, window_seconds
            )
            if retry_after is not None:
                await self._send_rate_limit_response(send, retry_after)
                return
            await self.app(scope, receive, send)
            return

        async with self._lock:
            timestamps = self._requests[identifier]

            while timestamps and timestamps[0] <= window_start:
                timestamps.popleft()

            if len(timestamps) >= request_limit:
                retry_after = max(
                    1,
                    math.ceil(window_seconds - (now - timestamps[0])),
                )
            else:
                timestamps.append(now)

        if retry_after is not None:
            await self._send_rate_limit_response(send, retry_after)
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _get_identifier(scope: Scope) -> str:
        """优先根据 Bearer Token 摘要识别调用方，否则使用客户端地址。"""
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        authorization = headers.get("authorization", "").strip()

        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
            if token:
                digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
                return f"session:{digest}"

        client = scope.get("client")
        client_host = client[0] if client else "unknown"
        return f"ip:{client_host}"

    @staticmethod
    async def _send_rate_limit_response(
        send: Send,
        retry_after: int,
    ) -> None:
        """返回标准 429 JSON 响应和重试时间。"""
        body = json.dumps(
            {
                "detail": "Too many requests",
                "retry_after": retry_after,
            }
        ).encode("utf-8")

        start_message: Message = {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"retry-after", str(retry_after).encode("ascii")),
            ],
        }
        body_message: Message = {
            "type": "http.response.body",
            "body": body,
        }

        await send(start_message)
        await send(body_message)
