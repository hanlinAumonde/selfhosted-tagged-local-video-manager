"""A migration inside one bucket is copied by the storage, not through the worker.

The server-side copy stands in for the streamed copy of the first phase only: it still
holds its slots, still reports progress, can still be cancelled, and the source keeps its
key until the third phase.
"""

import asyncio
from pathlib import Path

import pytest
from beanie.operators import Set

from src.features.catalog.video import VideoModel
from src.features.migration.migration_task import MigrationTaskModel
from src.platform.jobs.task_model import TaskStatus

pytestmark = pytest.mark.unit

SOURCE_DB = "Test-category/Test-resource/movie_a.mp4"
SHELF_DB = "Test-category/Test-resource/shelf/movie_a.mp4"
CONTENT = b"a" * 100  # what local_resource_dir puts in movie_a.mp4
EXISTING = b"existing video"
PART_SIZE = 10


async def _drain(gen) -> None:
    async for _ in gen:
        pass


def _copies_by_itself(handler, monkeypatch, after_first_part=None) -> list[int]:
    """
    Make a local mount behave like one bucket: no link, no rename, but its own copy.

    Like a multipart upload, nothing lands at the target until every part is in.

    :return: The progress reported so far, one entry per part the storage copied.
    """
    reported: list[int] = []

    async def copy_server_side(source, target, on_progress):
        data = Path(source).read_bytes()
        for end in range(PART_SIZE, len(data) + PART_SIZE, PART_SIZE):
            reported.append(min(end, len(data)))
            on_progress(reported[-1])
            if end == PART_SIZE and after_first_part is not None:
                await after_first_part()
        Path(target).write_bytes(data)
        return True

    monkeypatch.setattr(handler, "moves_without_copying", False)
    monkeypatch.setattr(handler, "copy_server_side", copy_server_side)
    return reported


def _forbid_reading_through_the_worker(handler, monkeypatch) -> None:
    async def refuse(path, chunk_size=1024 * 1024):
        raise AssertionError(f"{path} was read through the worker")
        yield

    monkeypatch.setattr(handler, "read_file_streaming", refuse)


def _cancel_and_wait_for_the_worker_to_notice(svc, task):
    async def cancel():
        await MigrationTaskModel.find_one(MigrationTaskModel.id == task.id).update(
            Set({MigrationTaskModel.cancel_requested: True})
        )
        while not svc._cancel_requested.get(str(task.id)):
            await asyncio.sleep(0.01)

    return cancel


@pytest.fixture
def bucket(two_cat_handler_service):
    """The handler of the mount standing in for one bucket."""
    return two_cat_handler_service.get_handler("Test-category")


class TestCopyingInsideTheStorage:
    """S3 stand-in: a real local mount that cannot link or rename but can copy by itself."""

    # Scenario: a migration inside one storage never reads the file through the worker
    #   Given a mount whose storage copies server-side and cannot link or rename
    #   And reading the source through the worker fails
    #   And a video "movie_a.mp4" and a sub-directory on that mount
    #   When its migration into the sub-directory runs to the end
    #   Then the stored status is COMPLETED
    #   And the target file holds the source's content
    #   And the source file no longer exists
    #   And the video record points at the target path
    #   And the stored bytes_transferred equals the file size
    async def test_a_migration_inside_one_storage_is_copied_by_the_storage(
        self, two_cat_migration_svc, bucket, shelving_task, local_resource_dir, shelf,
        monkeypatch,
    ):
        _copies_by_itself(bucket, monkeypatch)
        _forbid_reading_through_the_worker(bucket, monkeypatch)

        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        stored = await MigrationTaskModel.get(shelving_task.id)
        assert stored.error_message is None
        assert stored.status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").read_bytes() == CONTENT
        assert not (local_resource_dir / "movie_a.mp4").exists()
        assert await VideoModel.find_one(VideoModel.path == SHELF_DB) is not None
        assert stored.bytes_transferred == 100

    # Scenario: storage that declines the server-side copy is streamed instead
    #   Given a mount that cannot link or rename, and declines to copy server-side
    #       (as S3 does for two mounts on different buckets)
    #   And a video and a sub-directory on that mount
    #   When its migration runs to the end
    #   Then the storage was asked once
    #   And the stored status is COMPLETED
    #   And the target file holds the source's content
    #   And the source file no longer exists
    async def test_a_declined_server_side_copy_falls_back_to_streaming(
        self, two_cat_migration_svc, bucket, shelving_task, local_resource_dir, shelf,
        monkeypatch,
    ):
        asked: list[tuple[str, str]] = []

        async def decline(source, target, on_progress):
            asked.append((source, target))
            return False

        monkeypatch.setattr(bucket, "moves_without_copying", False)
        monkeypatch.setattr(bucket, "copy_server_side", decline)

        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert len(asked) == 1
        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").read_bytes() == CONTENT
        assert not (local_resource_dir / "movie_a.mp4").exists()

    # Scenario: a migration between categories is never copied server-side
    #   Given a source category whose storage would copy server-side
    #   And a target directory in another category
    #   When its migration runs to the end
    #   Then the stored status is COMPLETED
    #   And the source storage was never asked for a server-side copy — the target path
    #       means nothing to it
    #   And the target file holds the source's content
    async def test_a_migration_between_categories_is_not_copied_server_side(
        self, two_cat_migration_svc, bucket, video_factory, task_factory, target_dir,
        monkeypatch,
    ):
        reported = _copies_by_itself(bucket, monkeypatch)
        await video_factory(name="movie_a", path=SOURCE_DB)
        task = await task_factory(source_path=SOURCE_DB)

        await _drain(two_cat_migration_svc.run_task(str(task.id)))

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.COMPLETED
        assert reported == []
        assert (target_dir / "movie_a.mp4").read_bytes() == CONTENT


class TestStoppingAServerSideCopy:
    # Scenario: a cancel raised while the storage is copying stops it
    #   Given a mount whose storage copies server-side in ten parts
    #   And the web process raises cancel_requested after the first part
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the storage stopped before copying every part
    #   And the target file does not exist
    #   And the source file still holds its content
    #   And the video record still points at the source path
    async def test_a_cancel_during_a_server_side_copy_keeps_the_source(
        self, two_cat_migration_svc, bucket, shelving_task, local_resource_dir, shelf,
        monkeypatch,
    ):
        reported = _copies_by_itself(
            bucket, monkeypatch,
            after_first_part=_cancel_and_wait_for_the_worker_to_notice(
                two_cat_migration_svc, shelving_task
            ),
        )

        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.CANCELLED
        assert 1 <= len(reported) < 10
        assert not (shelf / "movie_a.mp4").exists()
        assert (local_resource_dir / "movie_a.mp4").read_bytes() == CONTENT
        assert await VideoModel.find_one(VideoModel.path == SOURCE_DB) is not None

    # Scenario: a server-side copy that fails leaves the task retryable
    #   Given a mount whose storage fails in the middle of a server-side copy
    #   When the worker runs the task to the end
    #   Then the stored status is FAILED with failed_step PROCESSING
    #   And the source file still holds its content
    #   And the video record still points at the source path
    async def test_a_failed_server_side_copy_fails_the_task_and_keeps_the_source(
        self, two_cat_migration_svc, bucket, shelving_task, local_resource_dir, monkeypatch,
    ):
        async def fail():
            raise OSError("storage refused the part")

        _copies_by_itself(bucket, monkeypatch, after_first_part=fail)

        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        stored = await MigrationTaskModel.get(shelving_task.id)
        assert stored.status == TaskStatus.FAILED
        assert stored.failed_step == TaskStatus.PROCESSING
        assert "storage refused the part" in stored.error_message
        assert (local_resource_dir / "movie_a.mp4").read_bytes() == CONTENT
        assert await VideoModel.find_one(VideoModel.path == SOURCE_DB) is not None

    # Scenario: an overwrite cancelled mid-copy keeps the replaced video
    #   Given a mount whose storage copies server-side and writes atomically, like S3
    #   And an overwrite migration onto the path video "existing" occupies
    #   And the web process raises cancel_requested after the first part
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the target still holds the content of "existing"
    async def test_a_cancelled_server_side_overwrite_keeps_the_replaced_video(
        self, two_cat_migration_svc, bucket, video_factory, task_factory, shelf, monkeypatch,
    ):
        (shelf / "movie_a.mp4").write_bytes(EXISTING)
        await video_factory(name="incoming", path=SOURCE_DB)
        await video_factory(name="existing", path=SHELF_DB)
        task = await task_factory(
            source_path=SOURCE_DB, target_path=SHELF_DB,
            target_category="Test-category", conflict_strategy="overwrite",
        )
        monkeypatch.setattr(bucket, "writes_atomically", True)
        _copies_by_itself(
            bucket, monkeypatch,
            after_first_part=_cancel_and_wait_for_the_worker_to_notice(two_cat_migration_svc, task),
        )

        await _drain(two_cat_migration_svc.run_task(str(task.id)))

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.CANCELLED
        assert (shelf / "movie_a.mp4").read_bytes() == EXISTING
