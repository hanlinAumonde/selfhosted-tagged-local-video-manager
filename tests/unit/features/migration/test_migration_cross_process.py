"""Migration actions issued by the web process, executed by a worker process.

The web process holds no in-memory state shared with the worker, so cancel and retry
must leave everything the worker needs on the task document.
"""

import pytest
from beanie.operators import Set

from src.errors import InputValidationError
from src.features.catalog.video import VideoModel
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus

pytestmark = pytest.mark.unit

SOURCE_DB = "Test-category/Test-resource/movie_a.mp4"
TARGET_DB = "Target-category/Target-resource/movie_a.mp4"


async def _drain(gen) -> None:
    async for _ in gen:
        pass


class TestCancel:
    async def test_cancelling_a_pending_task_settles_it_at_once(
        self, two_cat_migration_svc, init_db, task_factory, video_factory, target_dir,
    ):
        # Given a PENDING migration task
        await video_factory(name="movie_a", path=SOURCE_DB)
        task = await task_factory(source_path=SOURCE_DB, target_path=TARGET_DB)

        # When cancel_task is called
        await two_cat_migration_svc.cancel_task(str(task.id))

        # Then the stored status is CANCELLED with completed_at set
        stored = await MigrationTaskModel.get(task.id)
        assert stored.status == TaskStatus.CANCELLED
        assert stored.completed_at is not None
        # And a later run of that task copies nothing
        await _drain(two_cat_migration_svc.run_task(str(task.id)))
        assert not (target_dir / "movie_a.mp4").exists()

    async def test_cancelling_a_processing_task_raises_the_flag_on_the_document(
        self, two_cat_migration_svc, init_db, task_factory,
    ):
        # Given a migration task stored as PROCESSING
        task = await task_factory(status=TaskStatus.PROCESSING)

        # When cancel_task is called
        await two_cat_migration_svc.cancel_task(str(task.id))

        # Then the stored cancel_requested is True
        stored = await MigrationTaskModel.get(task.id)
        assert stored.cancel_requested is True
        # And the stored status is still PROCESSING
        assert stored.status == TaskStatus.PROCESSING

    async def test_cancelling_a_task_past_the_copy_is_rejected(
        self, two_cat_migration_svc, init_db, task_factory,
    ):
        # Given a migration task stored as UPDATING_DB
        task = await task_factory(status=TaskStatus.UPDATING_DB)

        # When cancel_task is called
        # Then InputValidationError is raised
        with pytest.raises(InputValidationError, match="does not allow cancellation"):
            await two_cat_migration_svc.cancel_task(str(task.id))
        # And the stored cancel_requested is still False
        assert (await MigrationTaskModel.get(task.id)).cancel_requested is False


class TestRetry:
    async def test_retry_stores_the_resume_point_and_clears_the_cancel_flag(
        self, two_cat_migration_svc, init_db, task_factory,
    ):
        # Given a FAILED migration task with failed_step UPDATING_DB and cancel_requested True
        task = await task_factory(
            status=TaskStatus.FAILED,
            failed_step=TaskStatus.UPDATING_DB.value,
            error_message="record update failed",
            cancel_requested=True,
        )

        # When prepare_retry is called
        await two_cat_migration_svc.prepare_retry(str(task.id))

        # Then the stored status is PENDING with resume_from UPDATING_DB
        stored = await MigrationTaskModel.get(task.id)
        assert stored.status == TaskStatus.PENDING
        assert stored.resume_from == TaskStatus.UPDATING_DB
        # And the stored cancel_requested is False
        assert stored.cancel_requested is False
        assert stored.error_message is None

    async def test_retried_task_resumes_where_it_failed_when_run(
        self, two_cat_migration_svc, init_db, task_factory, video_factory,
        local_resource_dir, target_dir,
    ):
        # Given a FAILED migration task with failed_step UPDATING_DB whose target is already copied
        await video_factory(name="movie_a", path=SOURCE_DB)
        (target_dir / "movie_a.mp4").write_bytes(b"copied")
        task = await task_factory(
            source_path=SOURCE_DB,
            target_path=TARGET_DB,
            status=TaskStatus.FAILED,
            failed_step=TaskStatus.UPDATING_DB.value,
        )

        # When prepare_retry is called and the task is then run
        await two_cat_migration_svc.prepare_retry(str(task.id))
        await _drain(two_cat_migration_svc.run_task(str(task.id)))

        # Then the copy phase is skipped and the task completes
        assert (target_dir / "movie_a.mp4").read_bytes() == b"copied"
        assert not (local_resource_dir / "movie_a.mp4").exists()
        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.COMPLETED


class TestCancelRacingTheEndOfTheCopy:
    """The copy only looks at the cancel flag between chunks. A cancel accepted after the
    last chunk must still win, or the user is told "cancelled" about a file that moved."""

    # Scenario: a cancel accepted after the last chunk was read still cancels the migration
    #   Given a PENDING migration of "movie_a.mp4" from Test-category to Target-category
    #   And the web process raises cancel_requested right after the last chunk is written
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the target file does not exist
    #   And the source file still exists
    #   And the video record still points at the source path
    async def test_cancel_accepted_after_the_last_chunk_still_cancels(
        self, two_cat_migration_svc, init_db, two_cat_handler_service,
        video_factory, task_factory, local_resource_dir, target_dir, monkeypatch,
    ):
        await video_factory(name="movie_a", path=SOURCE_DB)
        task = await task_factory(source_path=SOURCE_DB, target_path=TARGET_DB)

        target_handler = two_cat_handler_service.get_handler("Target-category")
        write_file_streaming = target_handler.write_file_streaming

        async def write_then_cancel(path, chunks):
            # Every chunk has been read and written by now, so the copy never sees this.
            await write_file_streaming(path, chunks)
            await MigrationTaskModel.find_one(MigrationTaskModel.id == task.id).update(
                Set({MigrationTaskModel.cancel_requested: True})
            )

        monkeypatch.setattr(target_handler, "write_file_streaming", write_then_cancel)

        await _drain(two_cat_migration_svc.run_task(str(task.id)))

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.CANCELLED
        assert not (target_dir / "movie_a.mp4").exists()
        assert (local_resource_dir / "movie_a.mp4").exists()
        assert await VideoModel.find_one(VideoModel.path == SOURCE_DB) is not None
