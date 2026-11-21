"""One video moved from one category to another: the web process creates the task, the
worker runs it, and the rest of the app has to see the video at its new home.
"""

import asyncio

from tests.integration.graphql_documents import (
    CANCEL_MIGRATION_TASK,
    GET_MIGRATION_TASKS,
    GET_VIDEO_BY_ID,
    MIGRATION_PROGRESS_SUBSCRIPTION,
    UPDATE_VIDEO_METADATA,
)
from tests.integration.helpers import assert_no_errors, browse_nodes, collect_stream
from tests.integration.migration.conftest import SOURCE_DIR, SUBSCRIPTION_TIMEOUT, TARGET_DIR


async def _listed_tasks(execute_gql) -> list[tuple[str, str]]:
    result = await execute_gql(GET_MIGRATION_TASKS, {"input": {}})
    assert_no_errors(result)
    return [(t["id"], t["status"]) for t in result.data["getMigrationTasks"]["tasks"]]


async def _is_locked(execute_gql, video_id: str) -> bool:
    result = await execute_gql(GET_VIDEO_BY_ID, {"videoId": video_id})
    assert_no_errors(result)
    return result.data["getVideoById"]["isLocked"]


class TestMigratedVideoFollowsItsFile:
    async def test_migrated_video_is_listed_in_the_target_and_gone_from_the_source(
        self, execute_gql, create_migration, drain_queue,
        integration_resource_dir, target_resource_dir,
    ):
        """
        Given alpha.mp4 (1000 bytes) discovered by browsing Test-category/Test-resource
        When a migration of alpha to Target-category/Target-resource is created through GraphQL
        And the worker runs the task id the queue received
        Then alpha.mp4 exists in the target directory and no longer in the source directory
        And browsing the target lists "alpha" under the same video id
        And browsing the source no longer lists "alpha"
        And the task list reports the task as COMPLETED
        """
        alpha_id = (await browse_nodes(execute_gql, SOURCE_DIR))["alpha"]["id"]

        task_id = await create_migration(alpha_id)
        await drain_queue()

        assert (target_resource_dir / "alpha.mp4").read_bytes() == b"a" * 1000
        assert not (integration_resource_dir / "alpha.mp4").exists()
        assert (await browse_nodes(execute_gql, TARGET_DIR))["alpha"]["id"] == alpha_id
        assert "alpha" not in await browse_nodes(execute_gql, SOURCE_DIR)
        assert await _listed_tasks(execute_gql) == [(task_id, "COMPLETED")]

    async def test_progress_subscription_follows_the_worker_to_completion(
        self, execute_gql, stream_gql, create_migration, drain_queue,
    ):
        """
        Given a migration of alpha.mp4 (1000 bytes) created through GraphQL
        When the web side subscribes to its progress while the worker runs the task
        Then the last frame the subscriber receives is COMPLETED
        And that frame reports 1000 bytes transferred out of 1000
        """
        alpha_id = (await browse_nodes(execute_gql, SOURCE_DIR))["alpha"]["id"]
        task_id = await create_migration(alpha_id)

        stream = await stream_gql(MIGRATION_PROGRESS_SUBSCRIPTION, {"input": {"taskId": task_id}})
        # The worker starts only after the subscription has opened on the queued task, so
        # every later frame has to travel from the worker to the web side.
        opening = await anext(stream)
        assert opening.data["migrationProgressSubscription"]["status"] == "PENDING"
        await drain_queue()
        events = await asyncio.wait_for(collect_stream(stream), timeout=SUBSCRIPTION_TIMEOUT)

        for event in events:
            assert_no_errors(event)
        last = events[-1].data["migrationProgressSubscription"]
        # BigInt fields travel as strings.
        assert (last["status"], last["bytesTransferred"], last["totalBytes"]) == (
            "COMPLETED", "1000", "1000",
        )


class TestMigrationLocksTheVideo:
    async def test_video_is_locked_while_queued_and_free_after_the_worker_finishes(
        self, execute_gql, create_migration, drain_queue,
    ):
        """
        Given a migration of alpha.mp4 created through GraphQL but not yet run by the worker
        Then browsing the source shows alpha as locked
        And getVideoById reports alpha as locked
        And updating alpha's metadata is rejected
        When the worker runs the task
        Then getVideoById reports alpha as unlocked
        """
        alpha_id = (await browse_nodes(execute_gql, SOURCE_DIR))["alpha"]["id"]
        await create_migration(alpha_id)

        assert (await browse_nodes(execute_gql, SOURCE_DIR))["alpha"]["isLocked"] is True
        assert await _is_locked(execute_gql, alpha_id) is True
        update = await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": alpha_id, "name": "Renamed while moving", "tags": [],
        }})
        assert update.errors
        assert "being migrated" in str(update.errors[0])

        await drain_queue()

        assert await _is_locked(execute_gql, alpha_id) is False

    async def test_cancelled_queued_migration_never_moves_the_file(
        self, execute_gql, create_migration, drain_queue,
        integration_resource_dir, target_resource_dir,
    ):
        """
        Given a migration of alpha.mp4 created through GraphQL but not yet run by the worker
        When the task is cancelled through GraphQL
        And the worker then receives the task id the queue already holds
        Then alpha.mp4 is still in the source directory and absent from the target
        And browsing the source lists alpha as unlocked
        And the task list reports the task as CANCELLED
        """
        alpha_id = (await browse_nodes(execute_gql, SOURCE_DIR))["alpha"]["id"]
        task_id = await create_migration(alpha_id)

        cancel = await execute_gql(CANCEL_MIGRATION_TASK, {"input": {"taskId": task_id}})
        assert_no_errors(cancel)
        await drain_queue()

        assert (integration_resource_dir / "alpha.mp4").read_bytes() == b"a" * 1000
        assert not (target_resource_dir / "alpha.mp4").exists()
        assert (await browse_nodes(execute_gql, SOURCE_DIR))["alpha"]["isLocked"] is False
        assert await _listed_tasks(execute_gql) == [(task_id, "CANCELLED")]
