"""定义可安全展示给用户的应用异常。"""


class LifePilotError(Exception):
    """表示应用能够识别并安全反馈的业务异常。"""

    default_user_message = "操作暂时无法完成，请稍后重试。"

    def __init__(self, technical_message: str, user_message: str | None = None) -> None:
        """分别保存技术错误信息和用户可见信息。"""
        super().__init__(technical_message)

        self.technical_message = technical_message
        self.user_message = (
            user_message if user_message is not None else self.default_user_message
        )


class ConfigurationError(LifePilotError):
    """表示应用配置缺失或无效。"""

    default_user_message = "应用配置无效，请检查 .env 文件。"


class ModelServiceError(LifePilotError):
    """表示语言模型初始化或调用失败。"""

    default_user_message = "模型服务暂时不可用，请稍后重试。"
