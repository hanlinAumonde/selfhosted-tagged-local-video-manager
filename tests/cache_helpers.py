"""Drive the in-process cache's clock so TTL behaviour can be asserted without sleeping."""

from loguru import logger

from src.platform.cache.cache_service import CacheService
from src.platform.cache.cachetools_cache import CachetoolsCache


def advance_cache_clock(cache: CacheService | CachetoolsCache, seconds: float) -> None:
    """Expire every entry that would have expired had `seconds` passed."""
    if isinstance(cache, CacheService):
        cache = cache._impl
    underlying = cache._cache
    underlying.expire(underlying.timer() + seconds)


class CapturedWarnings:
    """Collects loguru WARNING-or-above messages while active."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self._sink_id: int | None = None

    def __enter__(self) -> "CapturedWarnings":
        self._sink_id = logger.add(
            lambda message: self.messages.append(message.record["message"]),
            level="WARNING",
        )
        return self

    def __exit__(self, *exc) -> None:
        logger.remove(self._sink_id)
