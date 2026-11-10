"""An overwrite must not cost the replaced video until the migration can no longer stop.

Removing the replaced video's record belongs to the second phase. A migration that stops
during the first phase never gets there, so its file has to survive too.
"""

import asyncio
from functools import partial
from pathlib import Path

import pytest
from beanie.operators import Set

from src.features.catalog.video import VideoModel
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus
from src.platform.storage.base_resource_handler import BaseResourceHandler

pytestmark = pytest.mark.unit

SOURCE_DB = "Test-category/Test-resource/movie_a.mp4"
TARGET_DB = "Target-category/Target-resource/movie_a.mp4"
INCOMING = b"a" * 100  # what local_resource_dir puts in movie_a.mp4
EXISTING = b"existing video"


async def _drain(gen) -> None:
    async for _ in gen:
        pass


async def _raise_cancel_flag(task: MigrationTaskModel) -> None:
    await MigrationTaskModel.find_one(MigrationTaskModel.id == task.id).update(
        Set({MigrationTaskModel.cancel_requested: True})
    )


def _staging_file(directory: Path, task: MigrationTaskModel) -> Path:
    return directory / f".migrating-{task.id}.part"


def _entries(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


@pytest.fixture
async def overwrite_task(video_factory, task_factory, target_dir):
    """Video "incoming" on its way onto the path video "existing" occupies."""
    await video_factory(name="incoming", path=SOURCE_DB)
    await video_factory(name="existing", path=TARGET_DB, category="Target-category")
    (target_dir / "movie_a.mp4").write_bytes(EXISTING)
    return await task_factory(
        source_path=SOURCE_DB, target_path=TARGET_DB, conflict_strategy="overwrite",
    )


def _interrupt_reading_after_first_chunk(handler, monkeypatch, interrupt) -> None:
    """Make the source arrive in small chunks and run ``interrupt`` after the first."""
    read_file_streaming = handler.read_file_streaming

    async def read_in_small_chunks(path, chunk_size=1024 * 1024):
        first = True
        async for chunk in read_file_streaming(path, chunk_size=10):
            yield chunk
            if first:
                first = False
                await interrupt()

    monkeypatch.setattr(handler, "read_file_streaming", read_in_small_chunks)


def _cancel_mid_copy(svc, handler, task, monkeypatch) -> None:
    async def cancel_and_wait_for_the_worker_to_notice():
        await _raise_cancel_flag(task)
        while not svc._cancel_requested.get(str(task.id)):
            await asyncio.sleep(0.01)

    _interrupt_reading_after_first_chunk(handler, monkeypatch, cancel_and_wait_for_the_worker_to_notice)


class TestLocalStorageKeepsTheReplacedFile:
    # Scenario: a cancel in the middle of the copy keeps the replaced video
    #   Given video "incoming" at the source and video "existing" at the target path
    #   And an overwrite migration between two categories
    #   And the web process raises cancel_requested while the copy is running
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the target file still holds the content of "existing"
    #   And the source file still holds the content of "incoming"
    #   And the target directory holds no staging file
    async def test_a_cancel_during_the_copy_keeps_the_replaced_file(
        self, two_cat_migration_svc, two_cat_handler_service, overwrite_task,
        local_resource_dir, target_dir, monkeypatch,
    ):
        source_handler = two_cat_handler_service.get_handler("Test-category")
        _cancel_mid_copy(two_cat_migration_svc, source_handler, overwrite_task, monkeypatch)

        await _drain(two_cat_migration_svc.run_task(str(overwrite_task.id)))

        assert (await MigrationTaskModel.get(overwrite_task.id)).status == TaskStatus.CANCELLED
        assert (target_dir / "movie_a.mp4").read_bytes() == EXISTING
        assert (local_resource_dir / "movie_a.mp4").read_bytes() == INCOMING
        assert _entries(target_dir) == ["movie_a.mp4"]

    # Scenario: a failed copy keeps the replaced video
    #   Given video "incoming" at the source and video "existing" at the target path
    #   And an overwrite migration between two categories
    #   And reading the source fails halfway through the copy
    #   When the worker runs the task to the end
    #   Then the stored status is FAILED
    #   And the target file still holds the content of "existing"
    #   And the target directory holds no staging file
    async def test_a_failed_copy_keeps_the_replaced_file(
        self, two_cat_migration_svc, two_cat_handler_service, overwrite_task,
        target_dir, monkeypatch,
    ):
        async def fail():
            raise OSError("disk read failed")

        source_handler = two_cat_handler_service.get_handler("Test-category")
        _interrupt_reading_after_first_chunk(source_handler, monkeypatch, fail)

        await _drain(two_cat_migration_svc.run_task(str(overwrite_task.id)))

        assert (await MigrationTaskModel.get(overwrite_task.id)).status == TaskStatus.FAILED
        assert (target_dir / "movie_a.mp4").read_bytes() == EXISTING
        assert _entries(target_dir) == ["movie_a.mp4"]

    # Scenario: a cancel accepted after the last chunk keeps the replaced video
    #   Given video "incoming" at the source and video "existing" at the target path
    #   And the web process raises cancel_requested right after the last chunk is written
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the target file still holds the content of "existing"
    #   And the record of "existing" still exists
    async def test_a_cancel_accepted_after_the_last_chunk_keeps_the_replaced_file(
        self, two_cat_migration_svc, two_cat_handler_service, overwrite_task,
        target_dir, monkeypatch,
    ):
        target_handler = two_cat_handler_service.get_handler("Target-category")
        write_file_streaming = target_handler.write_file_streaming

        async def write_then_cancel(path, chunks):
            written = await write_file_streaming(path, chunks)
            await _raise_cancel_flag(overwrite_task)
            return written

        monkeypatch.setattr(target_handler, "write_file_streaming", write_then_cancel)

        await _drain(two_cat_migration_svc.run_task(str(overwrite_task.id)))

        assert (await MigrationTaskModel.get(overwrite_task.id)).status == TaskStatus.CANCELLED
        assert (target_dir / "movie_a.mp4").read_bytes() == EXISTING
        assert await VideoModel.find_one(VideoModel.path == TARGET_DB) is not None

    # Scenario: a worker that dies during the copy discards only its own staging file
    #   Given a task stored as PROCESSING with strategy "overwrite"
    #   And a partial staging file and video "existing" at the target path
    #   When recovery plans the task
    #   Then the staging file no longer exists
    #   And the target file still holds the content of "existing"
    async def test_recovering_a_crashed_copy_discards_only_the_staging_file(
        self, two_cat_migration_svc, overwrite_task, target_dir,
    ):
        await overwrite_task.set({MigrationTaskModel.status: TaskStatus.PROCESSING})
        staging = _staging_file(target_dir, overwrite_task)
        staging.write_bytes(b"partial")

        await two_cat_migration_svc.plan_recovery()

        assert not staging.exists()
        assert (target_dir / "movie_a.mp4").read_bytes() == EXISTING

    # Scenario: a worker that dies after the copy still publishes it
    #   Given a task stored as PROCESS_DONE with strategy "overwrite"
    #   And a complete staging file and video "existing" at the target path
    #   When recovery plans the task and the worker runs it
    #   Then the stored status is COMPLETED
    #   And the target file holds the content of "incoming"
    #   And the target directory holds no staging file
    async def test_a_crash_after_the_copy_still_publishes_the_staged_file(
        self, two_cat_migration_svc, overwrite_task, target_dir,
    ):
        await overwrite_task.set({MigrationTaskModel.status: TaskStatus.PROCESS_DONE})
        _staging_file(target_dir, overwrite_task).write_bytes(INCOMING)

        await two_cat_migration_svc.plan_recovery()
        await _drain(two_cat_migration_svc.run_task(str(overwrite_task.id)))

        assert (await MigrationTaskModel.get(overwrite_task.id)).status == TaskStatus.COMPLETED
        assert (target_dir / "movie_a.mp4").read_bytes() == INCOMING
        assert _entries(target_dir) == ["movie_a.mp4"]

    # Scenario: replaying the database phase after publishing changes nothing
    #   Given a task stored as FAILED at step UPDATING_DB with strategy "overwrite"
    #   And the staged file was already published to the target path
    #   When the task is retried and run
    #   Then the stored status is COMPLETED
    #   And the target file holds the content of "incoming"
    async def test_retrying_the_database_phase_after_publishing_succeeds(
        self, two_cat_migration_svc, overwrite_task, target_dir,
    ):
        await overwrite_task.set({
            MigrationTaskModel.status: TaskStatus.FAILED,
            MigrationTaskModel.failed_step: TaskStatus.UPDATING_DB.value,
        })
        (target_dir / "movie_a.mp4").write_bytes(INCOMING)

        await two_cat_migration_svc.prepare_retry(str(overwrite_task.id))
        await _drain(two_cat_migration_svc.run_task(str(overwrite_task.id)))

        assert (await MigrationTaskModel.get(overwrite_task.id)).status == TaskStatus.COMPLETED
        assert (target_dir / "movie_a.mp4").read_bytes() == INCOMING

    # Scenario: a completed overwrite replaces the file and leaves nothing behind
    #   Given video "incoming" at the source and video "existing" at the target path
    #   And an overwrite migration between two categories
    #   When the worker runs the task to the end
    #   Then the target file holds the content of "incoming"
    #   And the only entry in the target directory is the target file
    #   And only one video record has the target path
    async def test_a_completed_overwrite_leaves_no_staging_file(
        self, two_cat_migration_svc, overwrite_task, target_dir,
    ):
        await _drain(two_cat_migration_svc.run_task(str(overwrite_task.id)))

        assert (target_dir / "movie_a.mp4").read_bytes() == INCOMING
        assert _entries(target_dir) == ["movie_a.mp4"]
        assert await VideoModel.find({"path": TARGET_DB}).count() == 1

    # Scenario: an overwrite inside one mount is linked and replaces the file
    #   Given video "incoming" and video "existing" in two directories of one mount
    #   And an overwrite migration between those directories
    #   When the worker runs the task to the end
    #   Then the target file has the inode the source had
    #   And the only entry in the target directory is the target file
    async def test_an_overwrite_inside_one_mount_links_and_replaces(
        self, two_cat_migration_svc, video_factory, task_factory, local_resource_dir,
    ):
        target_db = "Test-category/Test-resource/shelf/movie_a.mp4"
        shelf = local_resource_dir / "shelf"
        shelf.mkdir()
        (shelf / "movie_a.mp4").write_bytes(EXISTING)
        await video_factory(name="incoming", path=SOURCE_DB)
        await video_factory(name="existing", path=target_db)
        task = await task_factory(
            source_path=SOURCE_DB, target_path=target_db,
            target_category="Test-category", conflict_strategy="overwrite",
        )
        source_inode = (local_resource_dir / "movie_a.mp4").stat().st_ino

        await _drain(two_cat_migration_svc.run_task(str(task.id)))

        assert (shelf / "movie_a.mp4").stat().st_ino == source_inode
        assert _entries(shelf) == ["movie_a.mp4"]


@pytest.fixture
def atomic_target(two_cat_handler_service, monkeypatch):
    """The target storage behaves like S3: nothing lands until the stream has ended."""
    handler = two_cat_handler_service.get_handler("Target-category")
    write_file_streaming = handler.write_file_streaming

    async def write_when_complete(path, chunks):
        received = [chunk async for chunk in chunks]

        async def replay():
            for chunk in received:
                yield chunk

        return await write_file_streaming(path, replay())

    monkeypatch.setattr(handler, "write_file_streaming", write_when_complete)
    monkeypatch.setattr(handler, "writes_atomically", True)
    # Atomic storage never stages, so like S3 it has nothing to publish a staged file with.
    monkeypatch.setattr(handler, "replace_file", partial(BaseResourceHandler.replace_file, handler))
    return handler


def _cancel_right_after_the_upload(handler, task, monkeypatch) -> None:
    write_file_streaming = handler.write_file_streaming

    async def write_then_cancel(path, chunks):
        written = await write_file_streaming(path, chunks)
        await _raise_cancel_flag(task)
        return written

    monkeypatch.setattr(handler, "write_file_streaming", write_then_cancel)


class TestAtomicStorageKeepsTheReplacedFile:
    """S3 stand-in: a real local target whose write only lands when the stream ends."""

    # Scenario: a cancelled upload leaves the replaced object alone
    #   Given an overwrite migration onto storage whose writes are atomic
    #   And video "existing" at the target path
    #   And the web process raises cancel_requested while the upload is running
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the target still holds the content of "existing"
    async def test_a_cancelled_upload_keeps_the_replaced_object(
        self, two_cat_migration_svc, two_cat_handler_service, atomic_target,
        overwrite_task, target_dir, monkeypatch,
    ):
        source_handler = two_cat_handler_service.get_handler("Test-category")
        _cancel_mid_copy(two_cat_migration_svc, source_handler, overwrite_task, monkeypatch)

        await _drain(two_cat_migration_svc.run_task(str(overwrite_task.id)))

        assert (await MigrationTaskModel.get(overwrite_task.id)).status == TaskStatus.CANCELLED
        assert (target_dir / "movie_a.mp4").read_bytes() == EXISTING

    # Scenario: a cancel that arrives after the upload completed is too late
    #   Given an overwrite migration onto storage whose writes are atomic
    #   And video "existing" at the target path
    #   And the web process raises cancel_requested right after the upload completes
    #   When the worker runs the task to the end
    #   Then the stored status is COMPLETED
    #   And the target holds the content of "incoming"
    #   And only one video record has the target path
    async def test_a_cancel_after_the_upload_completed_finishes_the_migration(
        self, two_cat_migration_svc, atomic_target, overwrite_task, target_dir, monkeypatch,
    ):
        _cancel_right_after_the_upload(atomic_target, overwrite_task, monkeypatch)

        await _drain(two_cat_migration_svc.run_task(str(overwrite_task.id)))

        assert (await MigrationTaskModel.get(overwrite_task.id)).status == TaskStatus.COMPLETED
        assert (target_dir / "movie_a.mp4").read_bytes() == INCOMING
        assert await VideoModel.find({"path": TARGET_DB}).count() == 1

    # Scenario: without an overwrite a late cancel still removes the upload
    #   Given a migration without a conflict strategy onto storage whose writes are atomic
    #   And the web process raises cancel_requested right after the upload completes
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the target does not exist
    async def test_a_late_cancel_without_overwrite_removes_the_upload(
        self, two_cat_migration_svc, atomic_target, video_factory, task_factory,
        target_dir, monkeypatch,
    ):
        await video_factory(name="incoming", path=SOURCE_DB)
        task = await task_factory(source_path=SOURCE_DB, target_path=TARGET_DB)
        _cancel_right_after_the_upload(atomic_target, task, monkeypatch)

        await _drain(two_cat_migration_svc.run_task(str(task.id)))

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.CANCELLED
        assert not (target_dir / "movie_a.mp4").exists()
