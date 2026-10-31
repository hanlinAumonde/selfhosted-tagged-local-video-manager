"""Unit tests for CacheService — backend selection from CacheConfig."""

import pytest

from src.config import CacheConfig
from src.platform.cache.cache_service import CacheService
from src.platform.cache.cachetools_cache import CachetoolsCache
from src.platform.cache.redis_cache import RedisCache

pytestmark = pytest.mark.unit


async def test_cachetools_backend_is_selected_by_default():
    # Given a CacheConfig left at its defaults
    # When a CacheService is built from it
    # Then the service is backed by CachetoolsCache
    svc = CacheService(config=CacheConfig())
    assert isinstance(svc._impl, CachetoolsCache)


async def test_redis_backend_is_selected_when_configured(redis_url, raw_redis, prefix):
    # Given a CacheConfig with cache_type "redis" pointing at a running Redis
    # When a CacheService is built from it
    # Then the service is backed by RedisCache
    # And a value written through the service appears in Redis under the configured prefix
    config = CacheConfig.model_validate(
        {"cache_type": "redis", "key_prefix": prefix, "redis": {"url": redis_url}}
    )
    svc = CacheService(config=config)
    try:
        assert isinstance(svc._impl, RedisCache)
        await svc.set("k", [1, 2], ttl=60)
        assert raw_redis.get(f"{prefix}:k") == "[1, 2]"
    finally:
        await svc.clear()
        await svc.close()


async def test_cachetools_backend_honours_the_configured_max_size():
    # Given a CacheConfig with cache_type "cachetools" and cachetools.max_size=2
    # When three different keys are written through the service
    # Then exactly two of them remain readable
    config = CacheConfig.model_validate(
        {"cache_type": "cachetools", "cachetools": {"max_size": 2}}
    )
    svc = CacheService(config=config)
    for key in ("a", "b", "c"):
        await svc.set(key, 1, ttl=600)
    survived = [k for k in ("a", "b", "c") if await svc.contains(k)]
    assert len(survived) == 2


async def test_operations_round_trip_through_the_service():
    # Given a CacheService on the default backend
    # When a value is set, read, checked, deleted and the cache cleared
    # Then each call is reflected by the next read through the same service
    svc = CacheService(config=CacheConfig())

    await svc.set("k", "v", ttl=60)
    assert await svc.get("k") == "v"
    assert await svc.contains("k") is True

    await svc.delete("k")
    assert await svc.contains("k") is False

    await svc.set_many({"a": 1, "b": 2}, ttl=60)
    assert await svc.get("a") == 1
    await svc.clear()
    assert await svc.get("a") is None
    assert await svc.get("b") is None


async def test_close_releases_the_redis_connection(redis_url, prefix):
    # Given a CacheService on the redis backend that has served at least one request
    # When close() is awaited
    # Then no error is raised and a second close() is also harmless
    config = CacheConfig.model_validate(
        {"cache_type": "redis", "key_prefix": prefix, "redis": {"url": redis_url}}
    )
    svc = CacheService(config=config)
    await svc.get("k")
    await svc.close()
    await svc.close()
