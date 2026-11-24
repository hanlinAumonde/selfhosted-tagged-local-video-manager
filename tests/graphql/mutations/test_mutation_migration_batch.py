"""The batch migration mutations: preflight, create, cancel, retry.

The batch service is a spec'd mock here; what these tests own is the resolver's part —
resolving video ids, handing every created or requeued child to the queue, and
announcing the children it settled.
"""

import time
from unittest.mock import AsyncMock, call

import pytest
from beanie import PydanticObjectId

from src.features.migration.migration_batch import (
    BatchCreation,
    BatchPreflightResult,
    BatchSummary,
    MigrationBatchModel,
    SkippedSource,
)
from src.features.migration.migration_service import MigrationPreflightResult
from src.features.migration.migration_task import MigrationTaskModel
from src.platform.jobs.task_model import TaskStatus
from src.platform.jobs.progress import ProgressFrame
from tests.graphql.helpers import (
    CANCEL_MIGRATION_BATCH,
    CREATE_MIGRATION_BATCH,
    MIGRATION_BATCH_PREFLIGHT,
    RETRY_MIGRATION_BATCH,
    assert_error_contains,
    assert_no_errors,
    make_migration_path_input,
)

pytestmark = pytest.mark.mutation

BATCH_ID = "65f000000000000000000b01"
TARGET = make_migration_path_input("Test-category/Test-resource")


def _preflight(size: int) -> MigrationPreflightResult:
    return MigrationPreflightResult(
        valid=True,
        source_file_size=size,
        conflict_exists=False,
        space_available=1000,
        space_sufficient=True,
        already_migrating=False,
        same_location=False,
    )


def _batch() -> MigrationBatchModel:
    return MigrationBatchModel(
        id=PydanticObjectId(BATCH_ID),
        target_dir="Target-category/Target-resource",
        target_category="Target-category",
        conflict_strategy=None,
        created_at=time.time(),
    )


def _child(name: str) -> MigrationTaskModel:
    now = time.time()
    return MigrationTaskModel(
        id=PydanticObjectId(),
        source_path=f"Test-category/Test-resource/{name}.mp4",
        source_category="Test-category",
        target_path=f"Target-category/Target-resource/{name}.mp4",
        target_category="Target-category",
        file_name=name,
        file_size=100,
        status=TaskStatus.PENDING,
        batch_id=PydanticObjectId(BATCH_ID),
        created_at=now,
        updated_at=now,
    )


def _summary(**counts) -> BatchSummary:
    fields = {"total": 2, "active": 0, "completed": 0, "failed": 0, "cancelled": 0}
    fields.update(counts)
    return BatchSummary(batch_id=BATCH_ID, **fields)


class TestMigrationBatchPreflight:
    async def test_returns_each_file_and_the_aggregate(
        self, execute_gql, mock_migration_batch_service, video_factory,
    ):
        """
        Scenario: the batch preflight is published per file plus in total
          Given videos "movie_a" and "movie_b"
          And a batch service whose preflight reports both valid, total size 300,
            space available 1000 and space sufficient
          When migrationBatchPreflight is called for both videos
          Then the result is valid with totalSize "300" and spaceSufficient true
          And it lists one item per video, each carrying that video's id and its result
        """
        movie_a = await video_factory(name="movie_a")
        movie_b = await video_factory(name="movie_b")
        mock_migration_batch_service.preflight = AsyncMock(return_value=BatchPreflightResult(
            valid=True,
            items=[_preflight(100), _preflight(200)],
            total_size=300,
            space_available=1000,
            space_sufficient=True,
        ))

        result = await execute_gql(MIGRATION_BATCH_PREFLIGHT, {"input": {
            "sourceVideoIds": [str(movie_a.id), str(movie_b.id)],
            "targetDirRelativePath": TARGET,
        }})

        assert_no_errors(result)
        data = result.data["migrationBatchPreflight"]
        assert (data["valid"], data["totalSize"], data["spaceSufficient"]) == (True, "300", True)
        assert [(i["sourceVideoId"], i["result"]["sourceFileSize"]) for i in data["items"]] == [
            (str(movie_a.id), "100"),
            (str(movie_b.id), "200"),
        ]
        sources = mock_migration_batch_service.preflight.await_args.args[0]
        assert [s.DB_format_path() for s in sources] == [movie_a.path, movie_b.path]

    async def test_an_unknown_video_id_is_rejected(
        self, execute_gql, mock_migration_batch_service, video_factory,
    ):
        """
        Scenario: every source must be an existing video
          Given video "movie_a" exists and "507f1f77bcf86cd799439011" matches no video
          When migrationBatchPreflight is called for both ids
          Then the response carries an error mentioning "Video not found"
        """
        movie_a = await video_factory(name="movie_a")
        videoId = "507f1f77bcf86cd799439011"  # This is a valid ObjectId format but does not exist in the database
        result = await execute_gql(MIGRATION_BATCH_PREFLIGHT, {"input": {
            "sourceVideoIds": [str(movie_a.id), videoId],
            "targetDirRelativePath": TARGET,
        }})

        assert_error_contains(result, f"Video with ID {videoId} not found")


class TestCreateMigrationBatch:
    async def test_every_created_child_is_handed_to_the_queue(
        self, execute_gql, mock_migration_batch_service, mock_migration_dispatcher, video_factory,
    ):
        """
        Scenario: all children are sent; the worker's window decides which run
          Given videos "movie_a", "movie_b" and "movie_c"
          And a batch service that creates a batch with three PENDING children
          When createMigrationBatch is called for the three videos
          Then each child's id is submitted to the migration queue once
          And the result carries the batch id and the three tasks
        """
        videos = [await video_factory(name=n) for n in ("movie_a", "movie_b", "movie_c")]
        children = [_child(n) for n in ("movie_a", "movie_b", "movie_c")]
        mock_migration_batch_service.create_batch = AsyncMock(
            return_value=BatchCreation(batch=_batch(), tasks=children, skipped=[])
        )

        result = await execute_gql(CREATE_MIGRATION_BATCH, {"input": {
            "sourceVideoIds": [str(v.id) for v in videos],
            "targetDirRelativePath": TARGET,
        }})

        assert_no_errors(result)
        assert mock_migration_dispatcher.submit.await_args_list == [call(str(c.id)) for c in children]
        data = result.data["createMigrationBatch"]
        assert data["batchId"] == BATCH_ID
        assert [(t["fileName"], t["batchId"]) for t in data["tasks"]] == [
            ("movie_a", BATCH_ID), ("movie_b", BATCH_ID), ("movie_c", BATCH_ID),
        ]

    async def test_skipped_files_are_reported(
        self, execute_gql, mock_migration_batch_service, video_factory,
    ):
        """
        Scenario: files that could not be added are listed with their reasons
          Given videos "movie_a" and "movie_b"
          And a batch service that creates one child for "movie_a" and skips "movie_b"
            with reason "the file already has an active migration task"
          When createMigrationBatch is called for both videos
          Then the result lists one task
          And it lists "movie_b"'s id as skipped with that reason
        """
        movie_a = await video_factory(name="movie_a")
        movie_b = await video_factory(name="movie_b")
        reason = "the file already has an active migration task"
        mock_migration_batch_service.create_batch = AsyncMock(return_value=BatchCreation(
            batch=_batch(),
            tasks=[_child("movie_a")],
            skipped=[SkippedSource(source_path=movie_b.path, reason=reason)],
        ))

        result = await execute_gql(CREATE_MIGRATION_BATCH, {"input": {
            "sourceVideoIds": [str(movie_a.id), str(movie_b.id)],
            "targetDirRelativePath": TARGET,
        }})

        assert_no_errors(result)
        data = result.data["createMigrationBatch"]
        assert [t["fileName"] for t in data["tasks"]] == ["movie_a"]
        assert data["skipped"] == [{"sourceVideoId": str(movie_b.id), "reason": reason}]

    async def test_a_batch_with_nothing_to_move_submits_nothing(
        self, execute_gql, mock_migration_batch_service, mock_migration_dispatcher, video_factory,
    ):
        """
        Scenario: no child was created
          Given videos "movie_a" and "movie_b"
          And a batch service that skips both
          When createMigrationBatch is called for both videos
          Then the result's batchId is null
          And nothing is submitted to the migration queue
        """
        movie_a = await video_factory(name="movie_a")
        movie_b = await video_factory(name="movie_b")
        mock_migration_batch_service.create_batch = AsyncMock(return_value=BatchCreation(
            batch=None,
            tasks=[],
            skipped=[
                SkippedSource(source_path=movie_a.path, reason="busy"),
                SkippedSource(source_path=movie_b.path, reason="busy"),
            ],
        ))

        result = await execute_gql(CREATE_MIGRATION_BATCH, {"input": {
            "sourceVideoIds": [str(movie_a.id), str(movie_b.id)],
            "targetDirRelativePath": TARGET,
        }})

        assert_no_errors(result)
        assert result.data["createMigrationBatch"]["batchId"] is None
        mock_migration_dispatcher.submit.assert_not_awaited()


class TestCancelMigrationBatch:
    async def test_announces_each_child_it_settled(
        self, execute_gql, mock_migration_batch_service, mock_migration_service, mock_progress_publisher,
    ):
        """
        Scenario: children cancelled while queued get their final frame from the web process
          Given a batch service whose cancel settles children "t1" and "t2" of batch "B"
          And whose snapshot of each is a CANCELLED frame
          When cancelMigrationBatch is called for "B"
          Then a CANCELLED frame is published for "t1" and for "t2", each with batch id "B"
          And the result is the batch's summary
        """
        frames = {
            task_id: ProgressFrame(task_id=task_id, status="CANCELLED", current=0, total=100)
            for task_id in ("t1", "t2")
        }
        mock_migration_batch_service.cancel_batch = AsyncMock(return_value=["t1", "t2"])
        mock_migration_batch_service.summarize = AsyncMock(return_value=_summary(cancelled=2))
        mock_migration_service.build_snapshot = AsyncMock(side_effect=lambda task_id: frames[task_id])

        result = await execute_gql(CANCEL_MIGRATION_BATCH, {"input": {"batchId": BATCH_ID}})

        assert_no_errors(result)
        assert mock_progress_publisher.publish.await_args_list == [
            call(frames["t1"], batch_id=BATCH_ID),
            call(frames["t2"], batch_id=BATCH_ID),
        ]
        data = result.data["cancelMigrationBatch"]
        assert (data["batchId"], data["total"], data["cancelled"]) == (BATCH_ID, 2, 2)


class TestRetryMigrationBatch:
    async def test_every_requeued_child_is_handed_to_the_queue(
        self, execute_gql, mock_migration_batch_service, mock_migration_dispatcher,
    ):
        """
        Scenario: retrying a batch sends its requeued children
          Given a batch service whose retry requeues children "t1" and "t2" of batch "B"
          When retryMigrationBatch is called for "B"
          Then "t1" and "t2" are each submitted to the migration queue once
          And the result is the batch's summary
        """
        mock_migration_batch_service.retry_batch = AsyncMock(return_value=["t1", "t2"])
        mock_migration_batch_service.summarize = AsyncMock(return_value=_summary(active=2))

        result = await execute_gql(RETRY_MIGRATION_BATCH, {"input": {"batchId": BATCH_ID}})

        assert_no_errors(result)
        assert mock_migration_dispatcher.submit.await_args_list == [call("t1"), call("t2")]
        assert result.data["retryMigrationBatch"]["active"] == 2
