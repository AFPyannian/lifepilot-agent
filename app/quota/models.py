"""定义用户月度模型配额和当前周期用量。"""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class UserQuota:
    """管理员配置的可选月度硬上限；空值表示不限额。"""

    user_id: str
    monthly_request_limit: int | None
    monthly_token_limit: int | None
    updated_by: str | None
    updated_at: datetime


@dataclass(frozen=True)
class QuotaStatus:
    """当前 UTC 月份的配额配置和已预占/已结算用量。"""

    quota: UserQuota
    period_start: date
    request_count: int
    token_count: int
