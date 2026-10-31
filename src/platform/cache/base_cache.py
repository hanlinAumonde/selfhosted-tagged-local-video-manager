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
        ...

    @abstractmethod
    async def set(self, key: K, value: V, ttl: int) -> None:
        ...

    @abstractmethod
    async def set_many(self, items: Mapping[K, V], ttl: int) -> None:
        ...

    @abstractmethod
    async def delete(self, key: K) -> None:
        ...

    @abstractmethod
    async def contains(self, key: K) -> bool:
        ...

    @abstractmethod
    async def clear(self) -> None:
        ...

    async def close(self) -> None:
        return None
