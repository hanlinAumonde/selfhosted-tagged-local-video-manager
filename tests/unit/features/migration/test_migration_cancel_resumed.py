"""Cancelling a task that crash recovery or a retry put back in the queue.

Such a task reads PENDING, but only one that restarts from the copy is really unstarted.
"""

import pytest

from src.errors import InputValidationError
from src.features.catalog.video import VideoModel
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus

pytestmark = pytest.mark.unit

SOURCE_DB = "Test-category/Test-resource/movie_a.mp4"
TARGET_DB = "Target-category/Target-resource/movie_a.mp4"


async def _drain(gen) -> None:
    async for _ in gen:
        pass


class TestCancelOfAResumedTask:
    # Scenario: a task resuming at the database phase cannot be cancelled
    #   Given a video record at the source path of "movie_a.mp4"
    #   And a PENDING migration task with resume_from UPDATING_DB whose target is already copied
    #   When cancel_task is called
    #   Then InputValidationError names UPDATING_DB as the reason
    #   And the stored status is still PENDING
    #   And a later run of that task ends COMPLETED with the video record at the target path
    async def test_a_task_resuming_at_the_database_phase_cannot_be_cancelled(
        self, two_cat_migration_svc, init_db, task_factory, video_factory, target_dir,
    ):
        await video_factory(name="movie_a", path=SOURCE_DB)
        (target_dir / "movie_a.mp4").write_bytes(b"copied")
        task = await task_factory(
            source_path=SOURCE_DB, target_path=TARGET_DB, resume_from=TaskStatus.UPDATING_DB,
        )

        with pytest.raises(InputValidationError, match="does not allow cancellation: UPDATING_DB"):
            await two_cat_migration_svc.cancel_task(str(task.id))

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.PENDING
        await _drain(two_cat_migration_svc.run_task(str(task.id)))
        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.COMPLETED
        assert await VideoModel.find_one(VideoModel.path == TARGET_DB) is not None

    # Scenario: a task resuming at source deletion cannot be cancelled
    #   Given a video record already at the target path of "movie_a.mp4"
    #   And a PENDING migration task with resume_from DELETING_SOURCE
    #   And the file exists at both the source and the target
    #   When cancel_task is called
    #   Then InputValidationError names DELETING_SOURCE as the reason
    #   And a later run of that task ends COMPLETED with the source file gone
    async def test_a_task_resuming_at_source_deletion_cannot_be_cancelled(
        self, two_cat_migration_svc, init_db, task_factory, video_factory,
        local_resource_dir, target_dir,
    ):
        await video_factory(name="movie_a", path=TARGET_DB)
        (target_dir / "movie_a.mp4").write_bytes(b"copied")
        assert (local_resource_dir / "movie_a.mp4").exists()
        task = await task_factory(
            source_path=SOURCE_DB, target_path=TARGET_DB, resume_from=TaskStatus.DELETING_SOURCE,
        )

        with pytest.raises(InputValidationError, match="does not allow cancellation: DELETING_SOURCE"):
            await two_cat_migration_svc.cancel_task(str(task.id))

        await _drain(two_cat_migration_svc.run_task(str(task.id)))
        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.COMPLETED
        assert not (local_resource_dir / "movie_a.mp4").exists()

    # Scenario: a task rewound to the copy can still be cancelled
    #   Given a PENDING migration task with resume_from PROCESSING
    #   When cancel_task is called
    #   Then the stored status is CANCELLED
    #   And a later run of that task copies nothing
    async def test_a_task_rewound_to_the_copy_can_still_be_cancelled(
        self, two_cat_migration_svc, init_db, task_factory, video_factory, target_dir,
    ):
        await video_factory(name="movie_a", path=SOURCE_DB)
        task = await task_factory(
            source_path=SOURCE_DB, target_path=TARGET_DB, resume_from=TaskStatus.PROCESSING,
        )

        await two_cat_migration_svc.cancel_task(str(task.id))

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.CANCELLED
        await _drain(two_cat_migration_svc.run_task(str(task.id)))
        assert not (target_dir / "movie_a.mp4").exists()

    # Scenario: a retry that resumes past the copy cannot be cancelled
    #   Given a FAILED migration task with failed_step UPDATING_DB
    #   And prepare_retry has put it back in the queue
    #   When cancel_task is called
    #   Then InputValidationError names UPDATING_DB as the reason
    #   And the stored status is still PENDING
    async def test_a_retry_that_resumes_past_the_copy_cannot_be_cancelled(
        self, two_cat_migration_svc, init_db, task_factory,
    ):
        task = await task_factory(
            source_path=SOURCE_DB,
            target_path=TARGET_DB,
            status=TaskStatus.FAILED,
            failed_step=TaskStatus.UPDATING_DB.value,
        )
        await two_cat_migration_svc.prepare_retry(str(task.id))

        with pytest.raises(InputValidationError, match="does not allow cancellation: UPDATING_DB"):
            await two_cat_migration_svc.cancel_task(str(task.id))

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.PENDING
