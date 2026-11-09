"""Fixed-window rate limiting with a Redis backend and an in-process fallback.

Design decision
---------------
Redis is **optional**. When ``REDIS_URL`` is configured, counters live in Redis so limits
are shared across all API replicas. When it is not configured, or when Redis is
temporarily unreachable, the limiter degrades gracefully to a per-process in-memory
counter (logged as a warning) instead of failing requests. Authentication itself never
depends on Redis: token revocation is enforced through the database (see ``AuthService``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult: ...

    async def close(self) -> None: ...


class InMemoryRateLimiter:
    """Per-process fixed-window counter. Suitable for dev/tests or single-replica deploys."""

    def __init__(self, max_keys: int = 100_000) -> None:
        self._buckets: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()
        self._max_keys = max_keys

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.monotonic()
        async with self._lock:
            count, reset_at = self._buckets.get(key, (0, now + window_seconds))
            if now >= reset_at:
                count, reset_at = 0, now + window_seconds
            count += 1
            self._buckets[key] = (count, reset_at)
            if len(self._buckets) > self._max_keys:
                self._evict_expired(now)
        retry_after = max(int(reset_at - now + 0.999), 1)
        return RateLimitResult(count <= limit, max(limit - count, 0), retry_after)

    def _evict_expired(self, now: float) -> None:
        for bucket_key in [k for k, (_, reset) in self._buckets.items() if reset <= now]:
            self._buckets.pop(bucket_key, None)

    async def close(self) -> None:
        self._buckets.clear()


class RedisRateLimiter:
    """Shared fixed-window counter in Redis (INCR + EXPIRE in one pipeline)."""

    def __init__(self, redis: Redis, fallback: InMemoryRateLimiter | None = None) -> None:
        self._redis = redis
        self._fallback = fallback or InMemoryRateLimiter()

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        redis_key = f"ratelimit:{key}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, window_seconds, nx=True)
                pipe.ttl(redis_key)
                count, _, ttl = await pipe.execute()
        except (RedisError, OSError) as exc:
            logger.warning(
                "redis unavailable, using in-memory rate limiter", extra={"error": str(exc)}
            )
            return await self._fallback.hit(key, limit, window_seconds)
        retry_after = int(ttl) if ttl and int(ttl) > 0 else window_seconds
        return RateLimitResult(int(count) <= limit, max(limit - int(count), 0), retry_after)

    async def close(self) -> None:
        await self._redis.aclose()


def build_rate_limiter(redis_url: str | None) -> RateLimiter:
    if not redis_url:
        logger.info("REDIS_URL not set; using in-memory rate limiter")
        return InMemoryRateLimiter()
    client = Redis.from_url(
        redis_url, socket_connect_timeout=1, socket_timeout=1, health_check_interval=30
    )
    return RedisRateLimiter(client)
