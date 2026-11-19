"""Several videos moved in one batch: the web process creates the children, the worker
works through them in its window, and the directories are refreshed once the batch settles.
"""

import asyncio

from tests.integration.graphql_documents import (
    CANCEL_MIGRATION_BATCH,
    CREATE_MIGRATION_BATCH,
    GET_MIGRATION_TASKS,
    MIGRATION_BATCH_PROGRESS,
)
from tests.integration.helpers import (
    assert_no_errors,
    browse_nodes,
    collect_stream,
    discover_videos,
)
from tests.integration.migration.conftest import SOURCE_DIR, SUBSCRIPTION_TIMEOUT, TARGET_DIR


async def _create_batch(execute_gql, video_ids: list[str]) -> str:
    result = await execute_gql(CREATE_MIGRATION_BATCH, {"input": {
        "sourceVideoIds": video_ids,
        "targetDirRelativePath": {"relativePath": TARGET_DIR},
    }})
    assert_no_errors(result)
    created = result.data["createMigrationBatch"]
    assert created["skipped"] == []
    return created["batchId"]


async def _batch_task_statuses(execute_gql, batch_id: str) -> list[tuple[str, str]]:
    result = await execute_gql(GET_MIGRATION_TASKS, {"input": {"batchId": batch_id}})
    assert_no_errors(result)
    return sorted((t["fileName"], t["status"]) for t in result.data["getMigrationTasks"]["tasks"])


class TestBatchMovesEveryFile:
    async def test_every_child_reaches_the_target_and_both_directories_are_refreshed(
        self, execute_gql, drain_queue, integration_resource_dir, target_resource_dir,
    ):
        """
        Given alpha.mp4 (1000 B) and beta.mp4 (2000 B) in Test-resource and
              drama/charlie.mp4 (3000 B), all discovered by browsing
        And browsing Test-category lists Test-resource at 10000 bytes
        When a batch moving the three to Target-category/Target-resource is created through GraphQL
        And the worker runs every task id the queue receives until the queue is empty
        Then the three files exist in the target directory and not in their source directories
        And browsing the target lists alpha, beta and charlie
        And browsing Target-category lists Target-resource at 6000 bytes
        And browsing Test-category lists Test-resource at 4000 bytes
        And the task list filtered by the batch reports three COMPLETED tasks
        """
        ids = await discover_videos(execute_gql, SOURCE_DIR, f"{SOURCE_DIR}/drama")
        assert (await browse_nodes(execute_gql, "Test-category"))["Test-resource"]["size"] == 10000

        batch_id = await _create_batch(execute_gql, [ids["alpha"], ids["beta"], ids["charlie"]])
        await drain_queue()

        assert sorted(p.name for p in target_resource_dir.iterdir()) == [
            "alpha.mp4", "beta.mp4", "charlie.mp4",
        ]
        assert not (integration_resource_dir / "alpha.mp4").exists()
        assert not (integration_resource_dir / "beta.mp4").exists()
        assert not (integration_resource_dir / "drama" / "charlie.mp4").exists()
        target = await browse_nodes(execute_gql, TARGET_DIR)
        assert {name: node["id"] for name, node in target.items()} == {
            "alpha": ids["alpha"], "beta": ids["beta"], "charlie": ids["charlie"],
        }
        assert (await browse_nodes(execute_gql, "Target-category"))["Target-resource"]["size"] == 6000
        assert (await browse_nodes(execute_gql, "Test-category"))["Test-resource"]["size"] == 4000
        assert await _batch_task_statuses(execute_gql, batch_id) == [
            ("alpha", "COMPLETED"), ("beta", "COMPLETED"), ("charlie", "COMPLETED"),
        ]

    async def test_batch_progress_subscription_ends_with_a_settled_summary(
        self, execute_gql, stream_gql, drain_queue,
    ):
        """
        Given a batch moving alpha.mp4 and beta.mp4 created through GraphQL
        When the web side subscribes to the batch's progress while the worker drains the queue
        Then the last event carries a summary with total 2, completed 2 and active 0
        """
        ids = await discover_videos(execute_gql, SOURCE_DIR, f"{SOURCE_DIR}/drama")
        batch_id = await _create_batch(execute_gql, [ids["alpha"], ids["beta"]])

        stream = await stream_gql(MIGRATION_BATCH_PROGRESS, {"input": {"batchId": batch_id}})
        # Opened on a batch with nothing run yet, so the settled summary can only arrive
        # with a child's terminal frame relayed from the worker.
        opening = (await anext(stream)).data["migrationBatchProgress"]["summary"]
        assert (opening["total"], opening["active"]) == (2, 2)
        await drain_queue()
        events = await asyncio.wait_for(
            collect_stream(stream), timeout=SUBSCRIPTION_TIMEOUT
        )

        for event in events:
            assert_no_errors(event)
        summary = events[-1].data["migrationBatchProgress"]["summary"]
        assert (summary["total"], summary["completed"], summary["active"]) == (2, 2, 0)


class TestCancelledBatch:
    async def test_cancelled_batch_leaves_every_queued_file_in_place(
        self, execute_gql, drain_queue, integration_resource_dir, target_resource_dir,
    ):
        """
        Given a batch moving alpha.mp4, beta.mp4 and drama/charlie.mp4 created through GraphQL
        When the batch is cancelled through GraphQL before the worker runs anything
        And the worker then runs every task id the queue already holds
        Then all three files are still in their source directories and none is in the target
        And the cancel response reports 3 cancelled and 0 active
        And the task list filtered by the batch reports three CANCELLED tasks
        """
        ids = await discover_videos(execute_gql, SOURCE_DIR, f"{SOURCE_DIR}/drama")
        batch_id = await _create_batch(execute_gql, [ids["alpha"], ids["beta"], ids["charlie"]])

        cancel = await execute_gql(CANCEL_MIGRATION_BATCH, {"input": {"batchId": batch_id}})
        assert_no_errors(cancel)
        await drain_queue()

        assert (integration_resource_dir / "alpha.mp4").exists()
        assert (integration_resource_dir / "beta.mp4").exists()
        assert (integration_resource_dir / "drama" / "charlie.mp4").exists()
        assert list(target_resource_dir.iterdir()) == []
        summary = cancel.data["cancelMigrationBatch"]
        assert (summary["cancelled"], summary["active"]) == (3, 0)
        assert await _batch_task_statuses(execute_gql, batch_id) == [
            ("alpha", "CANCELLED"), ("beta", "CANCELLED"), ("charlie", "CANCELLED"),
        ]
