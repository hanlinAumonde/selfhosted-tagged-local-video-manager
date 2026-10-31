from collections.abc import Mapping
from typing import Any, Optional
from src.config import CacheConfig
from src.platform.cache.base_cache import BaseCache, K, V
from src.platform.cache.cachetools_cache import CachetoolsCache
from src.platform.cache.redis_cache import RedisCache

# Keyed by CacheConfig.cache_type; its Literal already refuses unknown names at load time.
_CACHE_TYPES: dict[str, type[CachetoolsCache] | type[RedisCache]] = {
    "cachetools": CachetoolsCache,
    "redis": RedisCache,
}


class CacheService(BaseCache[K, V]):
    """Cache service that delegates to a concrete cache implementation based on config."""

    def __init__(self, config: CacheConfig):
        self._impl: BaseCache = _CACHE_TYPES[config.cache_type].from_config(config)

    async def get(self, key: K) -> Optional[Any]:
        return await self._impl.get(key)

    async def set(self, key: K, value: V, ttl: int) -> None:
        await self._impl.set(key, value, ttl)

    async def set_many(self, items: Mapping[K, V], ttl: int) -> None:
        await self._impl.set_many(items, ttl)

    async def delete(self, key: K) -> None:
        await self._impl.delete(key)

    async def contains(self, key: K) -> bool:
        return await self._impl.contains(key)

    async def clear(self) -> None:
        await self._impl.clear()

    async def close(self) -> None:
        await self._impl.close()
