from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from src.config import RedisConfig

#: Errors that mean "Redis is not answering". Anything else (a value that is not
#: JSON-serialisable, say) is a bug in the caller and must still raise.
REDIS_UNAVAILABLE = (RedisError, OSError)


class RedisService:
    """
    A process's one connection to Redis, and the one place its key names are built.

    Cache entries, task queues and progress channels all live in the same Redis under the
    same prefix; building every name here is what keeps them from landing on each other.
    The taskiq broker is the exception for the connection only: it insists on building its
    own pool from ``url``, but takes its key names from ``key()`` like everyone else.
    """

    def __init__(self, config: RedisConfig):
        """
        :param config: The ``redis`` section of the settings.
        :type config: RedisConfig
        """
        # No retries, and the same timeout for connecting and for every reply: a Redis that
        # stops answering costs each call one timeout, whether it is a cache read that will
        # degrade to a miss or a progress frame that will be dropped.
        self._client = Redis.from_url(
            config.url,
            socket_timeout=config.socket_timeout,
            socket_connect_timeout=config.socket_timeout,
            retry=Retry(NoBackoff(), 0),
            decode_responses=True,
        )
        self._url = config.url
        self._prefix = config.key_prefix

    @property
    def client(self) -> Redis:
        """The shared client. Calls on it raise ``REDIS_UNAVAILABLE`` errors when Redis is down."""
        return self._client

    @property
    def url(self) -> str:
        """Where Redis is, for a library that must open its own connections."""
        return self._url

    def key(self, *parts: str) -> str:
        """
        A Redis key, channel or group name: the configured prefix and each part, joined by colons.

        :param parts: The segments after the prefix, starting with a namespace from
            ``src.constants.redis``.
        :type parts: str
        :rtype: str
        """
        return ":".join((self._prefix, *parts))

    async def aclose(self) -> None:
        """Close the client's connections; called once, by whoever built this service."""
        await self._client.aclose()
