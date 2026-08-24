from langchain_deepseek import ChatDeepSeek

from app.config import Settings
from app.exceptions import ModelServiceError


def create_model( settings: Settings) -> ChatDeepSeek:
    """Create and configure the DeepSeek chat model."""
    try:
        return ChatDeepSeek(
            api_key=(
                settings
                .deepseek_api_key
                .get_secret_value()
            ),
            model=settings.deepseek_model,
            temperature=0,
            max_retries=2,
            streaming=True,
        )
    except Exception as error:
        raise ModelServiceError(
            "Failed to initialize DeepSeek."
        ) from error