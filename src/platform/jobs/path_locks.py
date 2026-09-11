from collections.abc import Iterable
from typing import Protocol, runtime_checkable


@runtime_checkable
class PathLockProvider(Protocol):
    """
    Something that can say which of a set of paths it is currently holding.

    Implemented by a feature that reserves files while a job runs. The protocol is bulk by
    design: marking a directory listing must cost one question, not one per row.
    """

    async def locked_paths(self, db_paths: Iterable[str]) -> set[str]:
        """
        Report which of the given paths this provider is holding.

        :param db_paths: Paths in DB format.
        :type db_paths: Iterable[str]
        :return: The subset of the input that this provider holds.
        :rtype: set[str]
        """
        ...


class PathLockRegistry:
    """
    Process-wide answer to "is this path spoken for by unfinished work?".

    Keeps the readers that display files independent of the features that reserve them:
    a reader asks the registry, and a feature that reserves paths registers itself at
    startup. Adding another kind of job that holds files means registering another
    provider, with no change to any reader.
    """

    def __init__(self):
        self._providers: dict[str, PathLockProvider] = {}

    def register(self, key: str, provider: PathLockProvider) -> None:
        """
        Make a provider part of every lookup from now on.

        Re-registering a key replaces the previous provider, so a repeated startup or a
        recovery pass does not end up asking the same source twice.

        :param key: Name of the provider, conventionally the executor key of the job type
            it speaks for.
        :type key: str
        :param provider: The provider to consult.
        :type provider: PathLockProvider
        :rtype: None
        """
        self._providers[key] = provider

    async def locked_paths(self, db_paths: Iterable[str]) -> set[str]:
        """
        Find which of the given paths any registered provider is holding.

        A failing provider is allowed to propagate rather than being skipped. Reporting
        "nothing is locked" because a lookup broke would let a delete through on a file
        that unfinished work still owns — silence here is data loss, not degraded service.

        :param db_paths: Paths in DB format. Empty or falsy entries are ignored.
        :type db_paths: Iterable[str]
        :return: The subset of the input that is held. Empty if nothing matches.
        :rtype: set[str]
        """
        wanted = {path for path in db_paths if path}
        if not wanted:
            return set()

        locked: set[str] = set()
        for provider in self._providers.values():
            locked |= await provider.locked_paths(wanted)
        return locked

    async def is_locked(self, db_path: str) -> bool:
        """
        Check a single path, for callers that guard one write at a time.

        :param db_path: Path in DB format.
        :type db_path: str
        :return: True if any registered provider holds it.
        :rtype: bool
        """
        return db_path in await self.locked_paths([db_path])
