import logging
import re
from time import perf_counter
from typing import Any
from uuid import uuid4


logger = logging.getLogger(
    "lifepilot.api.middleware"
)

REQUEST_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,100}$"
)


class RequestContextMiddleware:
    """
    为每次HTTP请求生成Request ID，
    并记录完整响应耗时。
    """

    def __init__(
        self,
        app: Any,
    ) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        if scope.get("type") != "http":
            await self.app(
                scope,
                receive,
                send,
            )
            return

        request_id = self._get_request_id(
            scope
        )

        method = scope.get(
            "method",
            "",
        )

        path = scope.get(
            "path",
            "",
        )

        started_at = perf_counter()
        status_code = 500
        response_completed = False

        scope.setdefault(
            "state",
            {},
        )

        scope["state"]["request_id"] = (
            request_id
        )

        async def send_with_request_id(
            message: dict[str, Any],
        ) -> None:
            nonlocal status_code, response_completed

            if (
                message["type"]
                == "http.response.start"
            ):
                status_code = message[
                    "status"
                ]

                headers = list(
                    message.get(
                        "headers",
                        [],
                    )
                )

                headers.append(
                    (
                        b"x-request-id",
                        request_id.encode(
                            "ascii"
                        ),
                    )
                )

                message["headers"] = headers

            await send(message)

            if (
                message["type"]
                == "http.response.body"
                and not message.get(
                    "more_body",
                    False,
                )
                and not response_completed
            ):
                response_completed = True

                duration_ms = (
                    perf_counter()
                    - started_at
                ) * 1000

                logger.info(
                    "Request completed "
                    "request_id=%s method=%s "
                    "path=%s status=%s "
                    "duration_ms=%.2f",
                    request_id,
                    method,
                    path,
                    status_code,
                    duration_ms,
                )

        try:
            await self.app(
                scope,
                receive,
                send_with_request_id,
            )

        except Exception:
            duration_ms = (
                perf_counter()
                - started_at
            ) * 1000

            logger.exception(
                "Request failed "
                "request_id=%s method=%s "
                "path=%s duration_ms=%.2f",
                request_id,
                method,
                path,
                duration_ms,
            )

            raise

    @staticmethod
    def _get_request_id(
        scope: dict[str, Any],
    ) -> str:
        headers = dict(
            scope.get(
                "headers",
                [],
            )
        )

        raw_request_id = headers.get(
            b"x-request-id"
        )

        if raw_request_id:
            try:
                request_id = (
                    raw_request_id.decode(
                        "ascii"
                    )
                )

            except UnicodeDecodeError:
                request_id = ""

            if REQUEST_ID_PATTERN.fullmatch(
                request_id
            ):
                return request_id

        return uuid4().hex