"""创建供 LifePilot Agent 使用的 DeepSeek 模型。"""

from langchain_deepseek import ChatDeepSeek

from app.config import Settings
from app.exceptions import ModelServiceError


def create_model(settings: Settings) -> ChatDeepSeek:
    """根据应用配置创建 DeepSeek 聊天模型。"""
    try:
        return ChatDeepSeek(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            temperature=0,
            max_retries=2,
            streaming=True,
        )
    except Exception as error:
        raise ModelServiceError("Failed to initialize DeepSeek.") from error
