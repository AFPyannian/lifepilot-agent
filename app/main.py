import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek


def create_model() -> ChatDeepSeek:
    """Create and configure the DeepSeek chat model."""
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY")
    model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

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


def main() -> None:
    """Send a test message to DeepSeek."""
    model = create_model()

    messages = [
        (
            "system",
            "你是 LifePilot，一个简洁、可靠的中文个人助理。",
        ),
        (
            "human",
            "请用一句话介绍你自己，并告诉我你当前能做什么。",
        ),
    ]

    print("正在请求 DeepSeek，请稍候……")

    response = model.invoke(messages)

    print("\nLifePilot：")
    print(response.content)


if __name__ == "__main__":
    main()