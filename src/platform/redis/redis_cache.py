import json
from collections.abc import Mapping
from typing import Any, Optional

from src.constants.redis import CACHE_NAMESPACE
from src.logger import get_logger
from src.platform.redis.redis_service import REDIS_UNAVAILABLE, RedisService

logger = get_logger("redis_cache")


class RedisCache:
    """
    Expiring JSON entries in Redis, under the cache namespace.

    Values are stored as JSON text and come back decoded, so a tuple reads back as a list.

    A cache is an optimisation, so an unreachable Redis degrades every call to a miss
    (reads) or a no-op (writes) with a warning, instead of failing the request.
    """

    def __init__(self, redis: RedisService):
        """
        :param redis: The process's Redis connection.
        :type redis: RedisService
        """
        self._redis = redis

    def _key(self, key: str) -> str:
        return self._redis.key(CACHE_NAMESPACE, key)

    async def get(self, key: str) -> Optional[Any]:
        """
        Read an entry.

        :param key: The entry's key, without prefix or namespace.
        :type key: str
        :return: The decoded value, or None if the entry is missing, expired, or Redis
            cannot be reached.
        :rtype: Optional[Any]
        """
        try:
            payload = await self._redis.client.get(self._key(key))
        except REDIS_UNAVAILABLE as e:
            logger.warning(f"Redis get failed, treating as a miss: {e!r}")
            return None
        return None if payload is None else json.loads(payload)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """
        Write an entry, replacing any previous value.

        :param key: The entry's key, without prefix or namespace.
        :type key: str
        :param value: A JSON-serialisable value.
        :type value: Any
        :param ttl: Seconds the entry lives. Required: the Redis evicts only keys that
            carry a TTL, which is what keeps it from evicting a task queue.
        :type ttl: int
        """
        payload = json.dumps(value)
        try:
            await self._redis.client.set(self._key(key), payload, ex=ttl)
        except REDIS_UNAVAILABLE as e:
            logger.warning(f"Redis set failed, entry not cached: {e!r}")

    async def set_many(self, items: Mapping[str, Any], ttl: int) -> None:
        """
        Write several entries that share one TTL, in one round trip.

        :param items: Key (without prefix or namespace) to JSON-serialisable value.
        :type items: Mapping[str, Any]
        :param ttl: Seconds every entry lives.
        :type ttl: int
        """
        if not items:
            return
        payloads = {self._key(k): json.dumps(v) for k, v in items.items()}
        try:
            # Not a transaction: cache entries have no atomicity requirement. Not MSET: it
            # cannot set a TTL.
            async with self._redis.client.pipeline(transaction=False) as pipe:
                for key, payload in payloads.items():
                    pipe.set(key, payload, ex=ttl)
                await pipe.execute()
        except REDIS_UNAVAILABLE as e:
            logger.warning(f"Redis set_many failed, {len(payloads)} entries not cached: {e!r}")

    async def delete(self, key: str) -> None:
        """
        Remove an entry; removing a missing one is not an error.

        :param key: The entry's key, without prefix or namespace.
        :type key: str
        """
        try:
            await self._redis.client.delete(self._key(key))
        except REDIS_UNAVAILABLE as e:
            logger.warning(f"Redis delete failed: {e!r}")
