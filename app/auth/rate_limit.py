"""提供进程内登录失败限流。"""

import hashlib
import math
import time
from collections import defaultdict, deque
from threading import Lock


class LoginRateLimiter:
    """按客户端地址和用户名限制连续登录失败。"""

    def __init__(
        self,
        max_failures: int,
        window_seconds: int,
    ) -> None:
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._failures: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    @staticmethod
    def build_key(
        client_host: str,
        username: str,
    ) -> str:
        """生成不保存明文用户名的限流键。"""
        normalized = username.strip().casefold()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"{client_host}:{digest}"

    def retry_after(self, key: str) -> int | None:
        """返回剩余限制秒数；未受限时返回 None。"""
        now = time.monotonic()
        window_start = now - self._window_seconds

        with self._lock:
            failures = self._failures[key]

            while failures and failures[0] <= window_start:
                failures.popleft()

            if len(failures) < self._max_failures:
                return None

            return max(
                1,
                math.ceil(self._window_seconds - (now - failures[0])),
            )

    def record_failure(self, key: str) -> None:
        """记录一次认证失败。"""
        with self._lock:
            self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        """登录成功后清除对应失败窗口。"""
        with self._lock:
            self._failures.pop(key, None)
