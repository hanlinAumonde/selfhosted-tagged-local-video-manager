from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Generic, TypeVar, Optional

K = TypeVar("K")
V = TypeVar("V")

class BaseCache(ABC, Generic[K, V]):
    """
    Values must be JSON-serialisable and come back JSON-decoded (a tuple reads back
    as a list) on every backend, so switching backends cannot change what a caller gets.
    """

    @abstractmethod
    async def get(self, key: K) -> Optional[Any]:
        """
        Read an entry.

        :param key: The entry's key, without the configured key prefix.
        :type key: K
        :return: The decoded value, or None if the entry is missing, expired, or the
            backend cannot be reached.
        :rtype: Optional[Any]
        """
        ...

    @abstractmethod
    async def set(self, key: K, value: V, ttl: int) -> None:
        """
        Write an entry, replacing any previous value.

        :param key: The entry's key, without the configured key prefix.
        :type key: K
        :param value: A JSON-serialisable value.
        :type value: V
        :param ttl: Seconds the entry lives.
        :type ttl: int
        """
        ...

    @abstractmethod
    async def set_many(self, items: Mapping[K, V], ttl: int) -> None:
        """
        Write several entries that share one TTL, in as few round trips as the backend
        allows.

        :param items: Key to JSON-serialisable value.
        :type items: Mapping[K, V]
        :param ttl: Seconds every entry lives.
        :type ttl: int
        """
        ...

    @abstractmethod
    async def delete(self, key: K) -> None:
        """
        Remove an entry; removing a missing one is not an error.

        :param key: The entry's key, without the configured key prefix.
        :type key: K
        """
        ...

    @abstractmethod
    async def contains(self, key: K) -> bool:
        """
        Whether an unexpired entry exists for a key.

        :param key: The entry's key, without the configured key prefix.
        :type key: K
        :return: False as well when the backend cannot be reached.
        :rtype: bool
        """
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Remove every entry under this cache's key prefix, and nothing else."""
        ...

    async def close(self) -> None:
        """Release the backend's connections. A no-op for a backend that holds none."""
        return None
