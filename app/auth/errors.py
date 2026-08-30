"""定义注册与邀请码领域异常。"""


class RegistrationClosedError(RuntimeError):
    """表示当前实例没有开放注册。"""


class RegistrationDeniedError(RuntimeError):
    """表示邀请码无效、过期、撤销或已经使用。"""


class UsernameUnavailableError(RuntimeError):
    """表示注册用户名不可用。"""
