"""定义模型凭据相关的安全业务异常。"""

from app.exceptions import LifePilotError


class CredentialError(LifePilotError):
    """表示不应输出底层异常链的凭据错误。"""


class CredentialValidationError(CredentialError):
    """表示用户提交的模型凭据未通过验证。"""

    default_user_message = "DeepSeek API Key 验证失败，请检查后重试。"


class CredentialNotConfiguredError(CredentialError):
    """表示当前用户没有可用的模型凭据。"""

    default_user_message = "当前账号尚未配置可用的 DeepSeek API Key。"


class CredentialDecryptionError(CredentialError):
    """表示密文损坏或对应主密钥版本不可用。"""

    default_user_message = "模型凭据暂时不可用，请重新保存 API Key。"
