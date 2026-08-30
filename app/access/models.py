"""定义访问能力、授权记录和授权判断结果。"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Capability(StrEnum):
    """LifePilot 当前可授权的能力。"""

    AGENT_CHAT = "agent.chat"
    MODEL_BYOK = "model.byok"
    MODEL_PLATFORM = "model.platform"


class EntitlementSource(StrEnum):
    """授权来源；预留订阅和活动来源但不实现计费。"""

    MIGRATION = "migration"
    ADMIN = "admin"
    SUBSCRIPTION = "subscription"
    PROMOTION = "promotion"


class EntitlementStatus(StrEnum):
    """授权记录状态。"""

    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True)
class EntitlementRecord:
    """表示一条可审计、可撤销、可过期的授权。"""

    id: str
    user_id: str
    capability: Capability
    source: EntitlementSource
    status: EntitlementStatus
    starts_at: datetime
    expires_at: datetime | None
    created_by: str | None
    created_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class AccessDecision:
    """访问策略返回的安全判断，不包含敏感内部信息。"""

    allowed: bool
    capability: Capability
    reason_code: str
    user_message: str
