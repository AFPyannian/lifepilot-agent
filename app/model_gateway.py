"""根据当前用户和模型模式安全调用 DeepSeek。"""

import logging
from collections.abc import Sequence
from typing import Any, Protocol

from langchain_core.messages import AnyMessage
from langchain_core.tools import BaseTool

from app.access.models import Capability
from app.access.policy import AccessPolicyProtocol
from app.config import Settings
from app.credentials.service import ProviderCredentialService
from app.exceptions import ModelServiceError
from app.model import create_model
from app.quota.service import QuotaService
from app.usage.models import ModelInvocationContext, UsageEvent
from app.usage.service import UsageTracker

logger = logging.getLogger("lifepilot.model_gateway")


class ModelGateway(Protocol):
    """描述 LangGraph 调用模型所需的网关接口。"""

    def invoke(
        self,
        *,
        context: ModelInvocationContext,
        tools: Sequence[BaseTool],
        messages: list[AnyMessage],
    ) -> AnyMessage:
        """按可信用户身份和选择的模式调用模型。"""
        ...


class StaticModelGateway:
    """适配现有测试中注入的静态聊天模型。"""

    def __init__(self, model: Any) -> None:
        self._model = model

    def invoke(
        self,
        *,
        context: ModelInvocationContext,
        tools: Sequence[BaseTool],
        messages: list[AnyMessage],
    ) -> AnyMessage:
        del context
        return self._model.bind_tools(tools).invoke(messages)


class DeepSeekModelGateway:
    """在平台 Key 和当前用户的加密 Key 之间进行安全路由。"""

    def __init__(
        self,
        *,
        settings: Settings,
        credential_service: ProviderCredentialService,
        access_policy: AccessPolicyProtocol,
        usage_tracker: UsageTracker,
        quota_service: QuotaService | None = None,
    ) -> None:
        self._settings = settings
        self._credential_service = credential_service
        self._access_policy = access_policy
        self._usage_tracker = usage_tracker
        self._quota_service = quota_service

    def invoke(
        self,
        *,
        context: ModelInvocationContext,
        tools: Sequence[BaseTool],
        messages: list[AnyMessage],
    ) -> AnyMessage:
        """每次请求重新解析凭据，避免跨用户缓存 Secret。"""
        credential_id: str | None = None
        event: UsageEvent | None = None

        if context.model_mode == "BYOK":
            self._access_policy.authorize(
                user_id=context.user_id,
                capability=Capability.MODEL_BYOK,
            )
            credential = self._credential_service.resolve_active(
                user_id=context.user_id
            )
            credential_id = credential.credential_id
            api_key = credential.secret
        elif context.model_mode == "PLATFORM":
            self._access_policy.authorize(
                user_id=context.user_id,
                capability=Capability.MODEL_PLATFORM,
            )
            if self._settings.deepseek_api_key is None:
                raise ModelServiceError("Platform credential is unavailable.")
            api_key = self._settings.deepseek_api_key
        else:
            raise ModelServiceError("Unknown model mode.")

        if self._quota_service is not None:
            self._quota_service.reserve_model_request(context.user_id)

        try:
            model = create_model(self._settings, api_key=api_key)
            event = self._usage_tracker.start(
                context=context,
                model=self._settings.deepseek_model,
            )
            response = model.bind_tools(tools).invoke(messages)
        except Exception as error:
            status_code = self._extract_status_code(error)

            if (
                context.model_mode == "BYOK"
                and credential_id is not None
                and status_code in {401, 403}
            ):
                try:
                    self._credential_service.mark_invalid(credential_id)
                except Exception:
                    logger.warning(
                        "Credential invalidation failed credential_id=%s",
                        credential_id,
                    )

            if event is not None:
                try:
                    self._usage_tracker.fail(
                        event,
                        self._error_code(status_code),
                    )
                except Exception:
                    logger.warning(
                        "Usage event finalization failed event_id=%s status=failed",
                        event.event_id,
                    )

            logger.warning(
                (
                    "DeepSeek invocation failed user_id=%s mode=%s "
                    "error_type=%s status_code=%s"
                ),
                context.user_id,
                context.model_mode,
                type(error).__name__,
                status_code,
            )
            raise ModelServiceError("DeepSeek invocation failed.") from None

        try:
            self._usage_tracker.succeed(event, response)
        except Exception:
            logger.warning(
                "Usage event finalization failed event_id=%s status=succeeded",
                event.event_id,
            )

        if self._quota_service is not None:
            try:
                self._quota_service.record_tokens(
                    context.user_id,
                    self._usage_tracker.total_tokens(response),
                )
            except Exception:
                logger.warning(
                    "Quota token accounting failed user_id=%s",
                    context.user_id,
                )

        if credential_id is not None:
            try:
                self._credential_service.mark_used(credential_id)
            except Exception:
                logger.warning(
                    "Credential last-used update failed credential_id=%s",
                    credential_id,
                )

        return response

    @staticmethod
    def _error_code(status_code: int | None) -> str:
        if status_code in {401, 403}:
            return "provider_auth"
        if status_code == 429:
            return "provider_rate_limit"
        if status_code is not None and status_code >= 500:
            return "provider_unavailable"
        return "provider_error"

    @staticmethod
    def _extract_status_code(error: Exception) -> int | None:
        """只读取结构化状态码，不解析或记录异常字符串。"""
        current: BaseException | None = error
        visited: set[int] = set()

        while current is not None and id(current) not in visited:
            visited.add(id(current))
            status_code = getattr(current, "status_code", None)

            if isinstance(status_code, int):
                return status_code

            response = getattr(current, "response", None)
            response_status = getattr(response, "status_code", None)

            if isinstance(response_status, int):
                return response_status

            current = (
                current.__cause__
                if current.__cause__ is not None
                else current.__context__
            )

        return None
