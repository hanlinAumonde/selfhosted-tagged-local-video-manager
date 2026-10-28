import json
from collections.abc import Mapping
from typing import Any, Optional

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from src.config import CacheConfig
from src.logger import get_logger
from src.platform.cache.base_cache import BaseCache, K, V

logger = get_logger("redis_cache")

# Errors that mean "Redis is not answering". Anything else (a value that is not
# JSON-serialisable, say) is a bug in the caller and must still raise.
_UNAVAILABLE = (RedisError, OSError)

_CLEAR_BATCH = 500


class RedisCache(BaseCache[K, V]):
    """
    A cache is an optimisation, so an unreachable Redis degrades every call to a miss
    (reads) or a no-op (writes) with a warning, instead of failing the request.
    """

    def __init__(self, url: str, socket_timeout: float, key_prefix: str):
        # No retries: a degraded read should cost one timeout, not several.
        self._client = Redis.from_url(
            url,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
            retry=Retry(NoBackoff(), 0),
            decode_responses=True,
        )
        self._prefix = key_prefix

    @classmethod
    def from_config(cls, config: CacheConfig) -> "RedisCache":
        return cls(
            url=config.redis.url,
            socket_timeout=config.redis.socket_timeout,
            key_prefix=config.key_prefix,
        )

    def _key(self, key: K) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: K) -> Optional[Any]:
        try:
            payload = await self._client.get(self._key(key))
        except _UNAVAILABLE as e:
            logger.warning(f"Redis get failed, treating as a miss: {e!r}")
            return None
        return None if payload is None else json.loads(payload)

    async def set(self, key: K, value: V, ttl: int) -> None:
        payload = json.dumps(value)
        try:
            await self._client.set(self._key(key), payload, ex=ttl)
        except _UNAVAILABLE as e:
            logger.warning(f"Redis set failed, entry not cached: {e!r}")

    async def set_many(self, items: Mapping[K, V], ttl: int) -> None:
        if not items:
            return
        payloads = {self._key(k): json.dumps(v) for k, v in items.items()}
        try:
            # One round trip for the whole batch. Not a transaction: cache entries
            # have no atomicity requirement. Not MSET: it cannot set a TTL.
            async with self._client.pipeline(transaction=False) as pipe:
                for key, payload in payloads.items():
                    pipe.set(key, payload, ex=ttl)
                await pipe.execute()
        except _UNAVAILABLE as e:
            logger.warning(f"Redis set_many failed, {len(payloads)} entries not cached: {e!r}")

    async def delete(self, key: K) -> None:
        try:
            await self._client.delete(self._key(key))
        except _UNAVAILABLE as e:
            logger.warning(f"Redis delete failed: {e!r}")

    async def contains(self, key: K) -> bool:
        try:
            return await self._client.exists(self._key(key)) > 0
        except _UNAVAILABLE as e:
            logger.warning(f"Redis exists failed, treating as absent: {e!r}")
            return False

    async def clear(self) -> None:
        # Only this prefix: the database may be shared, so FLUSHDB is not ours to call.
        try:
            batch: list[str] = []
            async for key in self._client.scan_iter(match=f"{self._prefix}:*", count=_CLEAR_BATCH):
                batch.append(key)
                if len(batch) >= _CLEAR_BATCH:
                    await self._client.unlink(*batch)
                    batch.clear()
            if batch:
                await self._client.unlink(*batch)
        except _UNAVAILABLE as e:
            logger.warning(f"Redis clear failed: {e!r}")

    async def close(self) -> None:
        await self._client.aclose()
