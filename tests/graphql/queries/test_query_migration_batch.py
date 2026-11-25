"""Batch children in the migration task list."""

import pytest

from src.platform.jobs.task_model import TaskStatus
from tests.graphql.helpers import GET_MIGRATION_TASKS, assert_no_errors
from tests.unit.features.migration.batch_helpers import add_child, make_batch

pytestmark = pytest.mark.query


class TestTasksOfABatch:
    async def test_tasks_can_be_filtered_by_batch(self, execute_gql, task_factory):
        """
        Scenario: listing the children of one batch
          Given batch "B1" with children "movie_a" PENDING and "movie_b" FAILED
          And batch "B2" with child "movie_c" PENDING
          And a migration task "movie_d" outside any batch
          When getMigrationTasks is called with batchId "B1"
          Then exactly "movie_a" and "movie_b" are returned
        """
        b1 = await make_batch()
        b2 = await make_batch()
        await add_child(task_factory, b1, "movie_a", TaskStatus.PENDING)
        await add_child(task_factory, b1, "movie_b", TaskStatus.FAILED)
        await add_child(task_factory, b2, "movie_c", TaskStatus.PENDING)
        await task_factory(
            source_path="Test-category/Test-resource/movie_d.mp4",
            target_path="Target-category/Target-resource/movie_d.mp4",
            file_name="movie_d",
        )

        result = await execute_gql(GET_MIGRATION_TASKS, {"input": {"batchId": str(b1.id)}})

        assert_no_errors(result)
        data = result.data["getMigrationTasks"]
        assert sorted(t["fileName"] for t in data["tasks"]) == ["movie_a", "movie_b"]
        assert data["totalCount"] == 2

    async def test_each_task_reports_its_batch(self, execute_gql, task_factory):
        """
        Scenario: a task says which batch it belongs to
          Given batch "B1" with child "movie_a"
          And a migration task "movie_d" outside any batch
          When getMigrationTasks is called without a filter
          Then "movie_a" has batchId "B1"
          And "movie_d" has a null batchId
        """
        b1 = await make_batch()
        await add_child(task_factory, b1, "movie_a")
        await task_factory(
            source_path="Test-category/Test-resource/movie_d.mp4",
            target_path="Target-category/Target-resource/movie_d.mp4",
            file_name="movie_d",
        )

        result = await execute_gql(GET_MIGRATION_TASKS, {"input": {}})

        assert_no_errors(result)
        batches = {t["fileName"]: t["batchId"] for t in result.data["getMigrationTasks"]["tasks"]}
        assert batches == {"movie_a": str(b1.id), "movie_d": None}
