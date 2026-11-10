"""A filesystem without hard links renames the file once a cancel can no longer land.

Nothing moves during the first phase, so a cancel, a failure or a crash there has nothing
to undo.
"""

import asyncio

import pytest
from beanie.operators import Set

from src.features.catalog.video import VideoModel
from src.features.migration.device_slots import device_of
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus

pytestmark = pytest.mark.unit

SOURCE_DB = "Test-category/Test-resource/movie_a.mp4"
SHELF_DB = "Test-category/Test-resource/shelf/movie_a.mp4"
CONTENT = b"a" * 100  # what local_resource_dir puts in movie_a.mp4


async def _drain(gen) -> None:
    async for _ in gen:
        pass


def _cancel_once_rename_is_found_possible(monkeypatch, handler, task) -> None:
    can_rename = handler.can_rename

    async def probe_then_cancel(source, target):
        possible = await can_rename(source, target)
        await MigrationTaskModel.find_one(MigrationTaskModel.id == task.id).update(
            Set({MigrationTaskModel.cancel_requested: True})
        )
        return possible

    monkeypatch.setattr(handler, "can_rename", probe_then_cancel)


@pytest.fixture
async def overwriting_task(video_factory, task_factory, shelf):
    """A PENDING overwrite of a different file in another directory of one mount."""
    await video_factory(name="movie_a", path=SOURCE_DB)
    (shelf / "movie_a.mp4").write_bytes(b"old")
    return await task_factory(
        source_path=SOURCE_DB,
        target_path=SHELF_DB,
        target_category="Test-category",
        conflict_strategy="overwrite",
    )


class TestRenamingInsteadOfCopying:
    # Scenario: a filesystem without hard links moves the file by renaming it
    #   Given a video "movie_a.mp4" and a sub-directory on the same mount
    #   And the filesystem rejects hard links
    #   When its migration into the sub-directory runs to the end
    #   Then the stored status is COMPLETED
    #   And the target file has the inode the source had
    #   And the source file no longer exists
    #   And the video record points at the target path
    #   And the stored bytes_transferred equals the file size
    #   And the last progress message reports no warning
    async def test_a_filesystem_without_hard_links_moves_the_file_by_renaming(
        self, two_cat_migration_svc, shelving_task, local_resource_dir, shelf, no_hard_links,
    ):
        source_inode = (local_resource_dir / "movie_a.mp4").stat().st_ino

        frames = [frame async for frame in two_cat_migration_svc.run_task(str(shelving_task.id))]

        stored = await MigrationTaskModel.get(shelving_task.id)
        assert stored.status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").stat().st_ino == source_inode
        assert not (local_resource_dir / "movie_a.mp4").exists()
        assert await VideoModel.find_one(VideoModel.path == SHELF_DB) is not None
        assert stored.bytes_transferred == 100
        assert frames[-1].message == "Task completed"

    # Scenario: an overwrite by rename replaces the old file
    #   Given a video and a different file already at its target path on the same mount
    #   And the filesystem rejects hard links
    #   And the task's conflict strategy is "overwrite"
    #   When its migration runs to the end
    #   Then the stored status is COMPLETED
    #   And the target file holds the source's content
    #   And no staging file is left in the target directory
    async def test_an_overwrite_by_rename_replaces_the_old_file(
        self, two_cat_migration_svc, overwriting_task, shelf, no_hard_links,
    ):
        await _drain(two_cat_migration_svc.run_task(str(overwriting_task.id)))

        assert (await MigrationTaskModel.get(overwriting_task.id)).status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").read_bytes() == CONTENT
        assert [entry.name for entry in shelf.iterdir()] == ["movie_a.mp4"]

    # Scenario: a filesystem with hard links keeps the source through the database phase
    #   Given a video file on a mount that supports hard links, with no video record
    #   When its migration runs and the database phase fails
    #   Then the stored status is FAILED
    #   And the source file still exists
    async def test_a_linked_migration_keeps_the_source_through_the_database_phase(
        self, two_cat_migration_svc, init_db, task_factory, local_resource_dir, shelf,
    ):
        task = await task_factory(
            source_path=SOURCE_DB, target_path=SHELF_DB, target_category="Test-category",
        )

        await _drain(two_cat_migration_svc.run_task(str(task.id)))

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.FAILED
        assert (local_resource_dir / "movie_a.mp4").read_bytes() == CONTENT


class TestNothingMovesWhileACancelCanLand:
    # Scenario: a cancel accepted before the rename leaves everything in place
    #   Given a video and a sub-directory on the same mount
    #   And the filesystem rejects hard links
    #   And the web process raises cancel_requested right after the rename is found possible
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the target file does not exist
    #   And the source file still holds its content
    #   And the video record still points at the source path
    async def test_a_cancel_accepted_before_the_rename_leaves_everything_in_place(
        self, two_cat_migration_svc, two_cat_handler_service, shelving_task,
        local_resource_dir, shelf, no_hard_links, monkeypatch,
    ):
        handler = two_cat_handler_service.get_handler("Test-category")
        _cancel_once_rename_is_found_possible(monkeypatch, handler, shelving_task)

        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.CANCELLED
        assert not (shelf / "movie_a.mp4").exists()
        assert (local_resource_dir / "movie_a.mp4").read_bytes() == CONTENT
        assert await VideoModel.find_one(VideoModel.path == SOURCE_DB) is not None

    # Scenario: a cancelled overwrite by rename keeps the old file
    #   Given a video and a different file already at its target path on the same mount
    #   And the filesystem rejects hard links
    #   And the task's conflict strategy is "overwrite"
    #   And the web process raises cancel_requested right after the rename is found possible
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the target file still holds its old content
    #   And the source file still holds its content
    async def test_a_cancelled_overwrite_by_rename_keeps_the_old_file(
        self, two_cat_migration_svc, two_cat_handler_service, overwriting_task,
        local_resource_dir, shelf, no_hard_links, monkeypatch,
    ):
        handler = two_cat_handler_service.get_handler("Test-category")
        _cancel_once_rename_is_found_possible(monkeypatch, handler, overwriting_task)

        await _drain(two_cat_migration_svc.run_task(str(overwriting_task.id)))

        assert (await MigrationTaskModel.get(overwriting_task.id)).status == TaskStatus.CANCELLED
        assert (shelf / "movie_a.mp4").read_bytes() == b"old"
        assert (local_resource_dir / "movie_a.mp4").read_bytes() == CONTENT


class TestRecoveringARename:
    # Scenario: a crash before the rename still moves the file
    #   Given a task stored as PROCESS_DONE with move_by_rename set
    #   And the file is still at the source
    #   When recovery plans the task and the worker runs it
    #   Then the stored status is COMPLETED
    #   And the target file holds the source's content
    #   And the source file no longer exists
    async def test_a_crash_before_the_rename_still_moves_the_file(
        self, two_cat_migration_svc, shelving_task, local_resource_dir, shelf,
    ):
        await shelving_task.set({
            MigrationTaskModel.status: TaskStatus.PROCESS_DONE,
            MigrationTaskModel.move_by_rename: True,
        })

        await two_cat_migration_svc.plan_recovery()
        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").read_bytes() == CONTENT
        assert not (local_resource_dir / "movie_a.mp4").exists()

    # Scenario: a crash after the rename does not rename again
    #   Given a task stored as UPDATING_DB with move_by_rename set
    #   And the file is already at the target and gone from the source
    #   And the video record still points at the source path
    #   When recovery plans the task and the worker runs it
    #   Then the stored status is COMPLETED
    #   And the target file holds its content
    #   And the video record points at the target path
    async def test_a_crash_after_the_rename_does_not_rename_again(
        self, two_cat_migration_svc, shelving_task, local_resource_dir, shelf,
    ):
        await shelving_task.set({
            MigrationTaskModel.status: TaskStatus.UPDATING_DB,
            MigrationTaskModel.move_by_rename: True,
        })
        (local_resource_dir / "movie_a.mp4").replace(shelf / "movie_a.mp4")

        await two_cat_migration_svc.plan_recovery()
        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").read_bytes() == CONTENT
        assert await VideoModel.find_one(VideoModel.path == SHELF_DB) is not None

    # Scenario: a rename refused because the file is in use can be retried
    #   Given a video and a sub-directory on the same mount
    #   And the filesystem rejects hard links
    #   And the rename at the database phase fails once, as it does while the file is open
    #   When the migration runs
    #   Then the stored status is FAILED with failed_step UPDATING_DB
    #   And the source file still holds its content
    #   And the video record still points at the source path
    #   And retrying the task ends COMPLETED with the file at the target
    async def test_a_rename_refused_while_the_file_is_in_use_can_be_retried(
        self, two_cat_migration_svc, two_cat_handler_service, shelving_task,
        local_resource_dir, shelf, no_hard_links, monkeypatch,
    ):
        handler = two_cat_handler_service.get_handler("Test-category")
        replace_file = handler.replace_file
        attempts = []

        async def in_use_the_first_time(source, target):
            attempts.append(target)
            if len(attempts) == 1:
                raise PermissionError(13, "The process cannot access the file")
            await replace_file(source, target)

        monkeypatch.setattr(handler, "replace_file", in_use_the_first_time)
        task_id = str(shelving_task.id)

        await _drain(two_cat_migration_svc.run_task(task_id))

        stored = await MigrationTaskModel.get(shelving_task.id)
        assert stored.status == TaskStatus.FAILED
        assert stored.failed_step == TaskStatus.UPDATING_DB.value
        assert (local_resource_dir / "movie_a.mp4").read_bytes() == CONTENT
        assert await VideoModel.find_one(VideoModel.path == SOURCE_DB) is not None

        await two_cat_migration_svc.prepare_retry(task_id)
        await _drain(two_cat_migration_svc.run_task(task_id))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").read_bytes() == CONTENT

    # Scenario: a file missing from both ends fails the migration
    #   Given a task stored as PROCESS_DONE with move_by_rename set
    #   And the file exists at neither the source nor the target
    #   When recovery plans the task and the worker runs it
    #   Then the stored status is FAILED
    #   And the video record still points at the source path
    async def test_a_file_missing_from_both_ends_fails_the_migration(
        self, two_cat_migration_svc, shelving_task, local_resource_dir, shelf,
    ):
        await shelving_task.set({
            MigrationTaskModel.status: TaskStatus.PROCESS_DONE,
            MigrationTaskModel.move_by_rename: True,
        })
        (local_resource_dir / "movie_a.mp4").unlink()

        await two_cat_migration_svc.plan_recovery()
        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.FAILED
        assert await VideoModel.find_one(VideoModel.path == SOURCE_DB) is not None


class TestDeviceSlots:
    # Scenario: a rename does not queue behind a busy device
    #   Given every slot of the mount's device is held by a running copy
    #   And the filesystem rejects hard links
    #   And a video and a sub-directory on that mount
    #   When its migration runs
    #   Then it reaches COMPLETED while the slot is still held
    async def test_a_rename_on_one_device_does_not_wait_for_a_busy_device(
        self, slotted_migration_svc, two_category_settings, shelving_task, no_hard_links,
    ):
        svc = slotted_migration_svc
        device = device_of(two_category_settings, "Test-category", "Test-resource")

        async with svc.copy_slots.hold([device]):
            await asyncio.wait_for(_drain(svc.run_task(str(shelving_task.id))), timeout=5)

            assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED
