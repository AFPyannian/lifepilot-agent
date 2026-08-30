"""定义访问控制领域异常。"""

from app.access.models import Capability
from app.exceptions import LifePilotError


class AccessDeniedError(LifePilotError):
    """表示用户未获得某项能力。"""

    default_user_message = "当前账号无权使用此功能。"

    def __init__(
        self,
        *,
        capability: Capability,
        reason_code: str,
        user_message: str,
    ) -> None:
        super().__init__(
            f"Access denied capability={capability.value} reason={reason_code}",
            user_message=user_message,
        )
        self.capability = capability
        self.reason_code = reason_code
