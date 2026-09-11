"""
MigrationService acting as a path-lock provider.

Same rules the module-level ``find_locked_paths`` used to carry, now reached through the
method ``PathLockRegistry`` calls. Single-path checks stay covered by ``TestIsFileLocked``
in test_migration_service.py.
"""

import pytest

from src.platform.jobs.path_locks import PathLockProvider
from src.platform.jobs.task_model import TaskStatus

pytestmark = pytest.mark.unit


class TestMigrationSatisfiesTheProviderProtocol:
    def test_the_service_is_a_path_lock_provider(self, migration_svc):
        """Registration would otherwise fail at startup rather than in a test."""
        assert isinstance(migration_svc, PathLockProvider)


class TestWhichPathsAMigrationHolds:
    """A file on its way out and a file about to be overwritten both need protecting, so a
    task holds its source, its target and its renamed target alike."""

    async def test_holds_source_target_and_renamed_target(
        self, migration_svc, init_db, task_factory,
    ):
        await task_factory(
            source_path="cat/res/a.mp4",
            target_path="cat/other/a.mp4",
            renamed_target_path="cat/other/a(1).mp4",
            status=TaskStatus.PROCESSING,
        )

        requested = [
            "cat/res/a.mp4", "cat/other/a.mp4", "cat/other/a(1).mp4", "cat/res/free.mp4",
        ]

        assert await migration_svc.locked_paths(requested) == {
            "cat/res/a.mp4", "cat/other/a.mp4", "cat/other/a(1).mp4",
        }

    @pytest.mark.parametrize(
        "status", [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
    )
    async def test_a_settled_task_holds_nothing(
        self, migration_svc, init_db, task_factory, status,
    ):
        await task_factory(source_path="cat/res/done.mp4", status=status)

        assert await migration_svc.locked_paths(["cat/res/done.mp4"]) == set()


class TestProviderReportsOnlyWhatWasAsked:
    """A matched task names paths the caller never asked about; returning those would make
    callers mark rows they are not displaying."""

    async def test_returns_the_requested_subset_and_nothing_more(
        self, migration_svc, init_db, task_factory,
    ):
        await task_factory(
            source_path="cat/res/locked.mp4",
            target_path="cat/other/locked.mp4",
            status=TaskStatus.PROCESSING,
        )

        result = await migration_svc.locked_paths(["cat/res/locked.mp4"])

        assert result == {"cat/res/locked.mp4"}

    async def test_returns_empty_for_an_empty_request(
        self, migration_svc, init_db, task_factory,
    ):
        await task_factory(source_path="cat/res/locked.mp4", status=TaskStatus.PROCESSING)

        assert await migration_svc.locked_paths([]) == set()
        assert await migration_svc.locked_paths(["", None]) == set()


class TestProviderIsBulkByDesign:
    """Marking a directory listing must cost one question, not one per row."""

    async def test_resolves_many_paths_in_one_call(
        self, migration_svc, init_db, task_factory,
    ):
        await task_factory(source_path="cat/res/v3.mp4", status=TaskStatus.PROCESSING)

        paths = [f"cat/res/v{i}.mp4" for i in range(10)]

        assert await migration_svc.locked_paths(paths) == {"cat/res/v3.mp4"}
