"""根据当前用户和模型模式安全调用 DeepSeek。"""

import logging
from collections.abc import Sequence
from typing import Any, Protocol

from langchain_core.messages import AnyMessage
from langchain_core.tools import BaseTool

from app.config import Settings
from app.credentials.models import ModelMode
from app.credentials.service import ProviderCredentialService
from app.exceptions import ModelServiceError
from app.model import create_model

logger = logging.getLogger("lifepilot.model_gateway")


class ModelAccessDeniedError(ModelServiceError):
    """表示请求的模型模式未启用或不可使用。"""

    default_user_message = "当前模型模式不可用。"


class ModelGateway(Protocol):
    """描述 LangGraph 调用模型所需的网关接口。"""

    def invoke(
        self,
        *,
        user_id: str,
        model_mode: ModelMode,
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
        user_id: str,
        model_mode: ModelMode,
        tools: Sequence[BaseTool],
        messages: list[AnyMessage],
    ) -> AnyMessage:
        del user_id, model_mode
        return self._model.bind_tools(tools).invoke(messages)


class DeepSeekModelGateway:
    """在平台 Key 和当前用户的加密 Key 之间进行安全路由。"""

    def __init__(
        self,
        *,
        settings: Settings,
        credential_service: ProviderCredentialService,
    ) -> None:
        self._settings = settings
        self._credential_service = credential_service

    def invoke(
        self,
        *,
        user_id: str,
        model_mode: ModelMode,
        tools: Sequence[BaseTool],
        messages: list[AnyMessage],
    ) -> AnyMessage:
        """每次请求重新解析凭据，避免跨用户缓存 Secret。"""
        credential_id: str | None = None

        if model_mode == "BYOK":
            if not self._settings.byok_enabled:
                raise ModelAccessDeniedError("BYOK mode is disabled.")

            credential = self._credential_service.resolve_active(user_id=user_id)
            credential_id = credential.credential_id
            api_key = credential.secret
        elif model_mode == "PLATFORM":
            if (
                not self._settings.platform_model_enabled
                or self._settings.deepseek_api_key is None
            ):
                raise ModelAccessDeniedError("Platform model is disabled.")

            api_key = self._settings.deepseek_api_key
        else:
            raise ModelAccessDeniedError("Unknown model mode.")

        try:
            model = create_model(self._settings, api_key=api_key)
            response = model.bind_tools(tools).invoke(messages)
        except ModelAccessDeniedError:
            raise
        except Exception as error:
            status_code = self._extract_status_code(error)

            if (
                model_mode == "BYOK"
                and credential_id is not None
                and status_code in {401, 403}
            ):
                self._credential_service.mark_invalid(credential_id)

            logger.warning(
                (
                    "DeepSeek invocation failed user_id=%s mode=%s "
                    "error_type=%s status_code=%s"
                ),
                user_id,
                model_mode,
                type(error).__name__,
                status_code,
            )
            raise ModelServiceError("DeepSeek invocation failed.") from None

        if credential_id is not None:
            self._credential_service.mark_used(credential_id)

        return response

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
