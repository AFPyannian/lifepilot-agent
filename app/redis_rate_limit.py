"""提供跨实例共享的 Redis 限流器。"""

import math
import time
from uuid import uuid4

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from app.auth.rate_limit import LoginRateLimiter

SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, window - (now - tonumber(oldest[2]))}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return {1, 0}
"""

FAILURE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return count
"""


class RedisApiRateLimiter:
    """用 Redis 有序集合实现跨实例滑动窗口限流。"""

    def __init__(self, redis_url: str, key_prefix: str) -> None:
        self._redis = AsyncRedis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix

    async def check(
        self, identifier: str, request_limit: int, window_seconds: int
    ) -> int | None:
        now_ms = int(time.time() * 1000)
        result = await self._redis.eval(
            SLIDING_WINDOW_SCRIPT,
            1,
            f"{self._key_prefix}:api:{identifier}",
            now_ms,
            window_seconds * 1000,
            request_limit,
            f"{now_ms}:{uuid4().hex}",
        )
        if int(result[0]) == 1:
            return None
        return max(1, math.ceil(int(result[1]) / 1000))

    async def close(self) -> None:
        await self._redis.aclose()

    async def ping(self) -> None:
        """验证 Redis 连接可用。"""
        await self._redis.ping()


class RedisLoginRateLimiter(LoginRateLimiter):
    """保持认证路由接口不变的 Redis 登录失败限流器。"""

    def __init__(
        self,
        redis_url: str,
        key_prefix: str,
        max_failures: int,
        window_seconds: int,
    ) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._key_prefix = key_prefix
        self._max_failures = max_failures
        self._window_seconds = window_seconds

    def _key(self, key: str) -> str:
        return f"{self._key_prefix}:auth:{key}"

    def retry_after(self, key: str) -> int | None:
        redis_key = self._key(key)
        pipe = self._redis.pipeline(transaction=False)
        pipe.get(redis_key)
        pipe.ttl(redis_key)
        value, ttl = pipe.execute()
        if int(value or 0) < self._max_failures:
            return None
        return max(1, int(ttl))

    def record_failure(self, key: str) -> None:
        self._redis.eval(
            FAILURE_SCRIPT,
            1,
            self._key(key),
            self._window_seconds,
        )

    def reset(self, key: str) -> None:
        self._redis.delete(self._key(key))

    def close(self) -> None:
        self._redis.close()
