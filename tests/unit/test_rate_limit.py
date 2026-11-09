"""Unit tests: rate limiter implementations (Redis is mocked or deliberately unreachable)."""

from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.rate_limit import InMemoryRateLimiter, RedisRateLimiter, build_rate_limiter


async def test_in_memory_counts_per_key() -> None:
    limiter = InMemoryRateLimiter()
    results = [await limiter.hit("k", limit=2, window_seconds=60) for _ in range(3)]
    assert [r.allowed for r in results] == [True, True, False]
    assert [r.remaining for r in results] == [1, 0, 0]
    assert results[2].retry_after >= 1
    assert (await limiter.hit("other", limit=2, window_seconds=60)).allowed
    await limiter.close()


async def test_in_memory_window_reset() -> None:
    limiter = InMemoryRateLimiter()
    assert (await limiter.hit("k", limit=1, window_seconds=1)).allowed
    assert not (await limiter.hit("k", limit=1, window_seconds=1)).allowed
    count, _ = limiter._buckets["k"]
    limiter._buckets["k"] = (count, 0.0)  # force expiry
    assert (await limiter.hit("k", limit=1, window_seconds=1)).allowed


async def test_in_memory_evicts_expired_keys_when_full() -> None:
    limiter = InMemoryRateLimiter(max_keys=2)
    await limiter.hit("a", limit=5, window_seconds=60)
    await limiter.hit("b", limit=5, window_seconds=60)
    limiter._buckets["a"] = (1, 0.0)  # expired
    await limiter.hit("c", limit=5, window_seconds=60)
    assert "a" not in limiter._buckets
    assert {"b", "c"} <= limiter._buckets.keys()


class FakePipeline:
    def __init__(self, store: dict[str, int], fail: bool) -> None:
        self.store, self.fail, self.key = store, fail, ""

    async def __aenter__(self) -> FakePipeline:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def incr(self, key: str) -> None:
        self.key = key

    def expire(self, key: str, seconds: int, nx: bool = False) -> None:
        pass

    def ttl(self, key: str) -> None:
        pass

    async def execute(self) -> list[int]:
        if self.fail:
            raise RedisConnectionError("redis down")
        self.store[self.key] = self.store.get(self.key, 0) + 1
        return [self.store[self.key], 1, 42]


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.store: dict[str, int] = {}
        self.fail = fail
        self.closed = False

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        return FakePipeline(self.store, self.fail)

    async def aclose(self) -> None:
        self.closed = True


async def test_redis_limiter_uses_shared_counter() -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(redis)  # type: ignore[arg-type]
    first = await limiter.hit("login:1.2.3.4", limit=1, window_seconds=60)
    second = await limiter.hit("login:1.2.3.4", limit=1, window_seconds=60)
    assert first.allowed
    assert not second.allowed
    assert second.retry_after == 42
    assert redis.store == {"ratelimit:login:1.2.3.4": 2}
    await limiter.close()
    assert redis.closed


async def test_redis_errors_fall_back_to_memory() -> None:
    limiter = RedisRateLimiter(FakeRedis(fail=True))  # type: ignore[arg-type]
    assert (await limiter.hit("k", limit=1, window_seconds=60)).allowed
    assert not (await limiter.hit("k", limit=1, window_seconds=60)).allowed


@pytest.mark.parametrize("url", ["redis://127.0.0.1:1/0"])
async def test_unreachable_redis_degrades_gracefully(url: str) -> None:
    # Nothing listens on port 1: requests must keep flowing via the in-memory fallback.
    limiter = build_rate_limiter(url)
    assert isinstance(limiter, RedisRateLimiter)
    assert (await limiter.hit("k", limit=1, window_seconds=60)).allowed
    assert not (await limiter.hit("k", limit=1, window_seconds=60)).allowed
    await limiter.close()
