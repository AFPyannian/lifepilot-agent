"""
创建和配置 DeepSeek 模型
"""
import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek


def create_model() -> ChatDeepSeek:
    """Create and configure the DeepSeek chat model."""
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY")
    model_name = os.getenv(
        "DEEPSEEK_MODEL",
        "deepseek-v4-flash",
    )

    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is missing. "
            "Please configure it in the .env file."
        )

    return ChatDeepSeek(
        model=model_name,
        temperature=0,
        max_retries=2,
    )