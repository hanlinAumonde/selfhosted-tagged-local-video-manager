import json
from collections.abc import Mapping
from typing import Any, NamedTuple, Optional
from cachetools import TLRUCache
from src.config import CacheConfig
from src.platform.cache.base_cache import BaseCache, K, V


class _Entry(NamedTuple):
    payload: str
    ttl: int


class CachetoolsCache(BaseCache[K, V]):

    def __init__(self, max_size: int, key_prefix: str):
        # TLRU rather than TTL: each entry carries its own lifetime, because the
        # caller decides it per write.
        self._cache: TLRUCache[str, _Entry] = TLRUCache(
            maxsize=max_size, ttu=lambda _key, entry, now: now + entry.ttl
        )
        self._prefix = key_prefix

    @classmethod
    def from_config(cls, config: CacheConfig) -> "CachetoolsCache":
        return cls(max_size=config.cachetools.max_size, key_prefix=config.key_prefix)

    def _key(self, key: K) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: K) -> Optional[Any]:
        entry = self._cache.get(self._key(key))
        return None if entry is None else json.loads(entry.payload)

    async def set(self, key: K, value: V, ttl: int) -> None:
        # Stored as JSON text so reads match the Redis backend and a caller mutating
        # its object afterwards cannot reach into the cache.
        self._cache[self._key(key)] = _Entry(json.dumps(value), ttl)

    async def set_many(self, items: Mapping[K, V], ttl: int) -> None:
        for key, value in items.items():
            await self.set(key, value, ttl)

    async def delete(self, key: K) -> None:
        self._cache.pop(self._key(key), None)

    async def contains(self, key: K) -> bool:
        return self._key(key) in self._cache

    async def clear(self) -> None:
        self._cache.clear()
