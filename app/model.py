"""创建供 LifePilot Agent 使用的 DeepSeek 模型。"""

from langchain_core.messages import HumanMessage
from langchain_deepseek import ChatDeepSeek
from pydantic import SecretStr

from app.config import Settings
from app.credentials.errors import CredentialValidationError
from app.exceptions import ModelServiceError


def create_model(
    settings: Settings,
    *,
    api_key: SecretStr | None = None,
    streaming: bool = True,
    max_retries: int | None = None,
    timeout: float | None = None,
) -> ChatDeepSeek:
    """使用明确指定或平台配置的凭据创建 DeepSeek 模型。"""
    active_api_key = api_key if api_key is not None else settings.deepseek_api_key

    if active_api_key is None or not active_api_key.get_secret_value().strip():
        raise ModelServiceError("DeepSeek API key is unavailable.")

    try:
        return ChatDeepSeek(
            api_key=active_api_key,
            model=settings.deepseek_model,
            temperature=0,
            timeout=(settings.deepseek_timeout_seconds if timeout is None else timeout),
            max_retries=(
                settings.deepseek_max_retries if max_retries is None else max_retries
            ),
            streaming=streaming,
        )
    except Exception:
        raise ModelServiceError("Failed to initialize DeepSeek.") from None


class DeepSeekCredentialValidator:
    """通过不进入追踪链的最小请求验证用户提交的 Key。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def validate(self, secret: SecretStr) -> None:
        """验证 Key，且不把供应商异常文本传播到日志或响应。"""
        try:
            model = create_model(
                self._settings,
                api_key=secret,
                streaming=False,
                max_retries=0,
                timeout=self._settings.credential_validation_timeout_seconds,
            )
            model.invoke(
                [HumanMessage(content="只回复 OK")],
                config={
                    "callbacks": [],
                    "tags": ["credential-validation"],
                },
            )
        except Exception:
            raise CredentialValidationError(
                "DeepSeek credential validation failed."
            ) from None
