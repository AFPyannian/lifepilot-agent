class LifePilotError(Exception):
    """预期的应用程序错误的父类"""

    default_user_message = (
        "操作暂时无法完成，请稍后重试。"
    )

    def __init__(self, technical_message: str, user_message: str | None = None) -> None:
        super().__init__(technical_message)

        self.technical_message = technical_message
        self.user_message = (
            user_message
            if user_message is not None
            else self.default_user_message
        )


class ConfigurationError(LifePilotError):
    """当应用程序配置无效时抛出此异常"""

    default_user_message = (
        "应用配置无效，请检查 .env 文件。"
    )


class ModelServiceError(LifePilotError):
    """当语言模型无法正常响应时抛出的异常"""

    default_user_message = (
        "模型服务暂时不可用，请稍后重试。"
    )