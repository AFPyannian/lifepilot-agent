"""执行用户模型配额预占和 Token 结算。"""

from datetime import UTC, date, datetime

from app.exceptions import QuotaExceededError
from app.quota.models import QuotaStatus, UserQuota
from app.repositories.protocols import QuotaRepositoryProtocol


class QuotaService:
    """按 UTC 自然月执行请求硬上限和 Token 消耗上限。"""

    def __init__(self, repository: QuotaRepositoryProtocol) -> None:
        self._repository = repository

    @staticmethod
    def current_period(now: datetime | None = None) -> date:
        current = now or datetime.now(UTC)
        return date(current.year, current.month, 1)

    def reserve_model_request(self, user_id: str) -> None:
        """原子预占一次请求，超限时返回安全业务错误。"""
        period = self.current_period()
        if not self._repository.reserve_model_request(user_id, period):
            raise QuotaExceededError("Monthly model quota exceeded.")

    def record_tokens(self, user_id: str, tokens: int | None) -> None:
        """在模型成功后累加可获得的实际 Token 数。"""
        if tokens is None or tokens <= 0:
            return
        self._repository.add_tokens(user_id, self.current_period(), tokens)

    def get_status(self, user_id: str) -> QuotaStatus:
        return self._repository.get_status(user_id, self.current_period())

    def set_quota(
        self,
        *,
        user_id: str,
        monthly_request_limit: int | None,
        monthly_token_limit: int | None,
        updated_by: str | None,
    ) -> UserQuota:
        return self._repository.set_quota(
            user_id=user_id,
            monthly_request_limit=monthly_request_limit,
            monthly_token_limit=monthly_token_limit,
            updated_by=updated_by,
        )
