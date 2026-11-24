"""Tests for the getMigrationTasks GraphQL query."""

import time

import pytest

from src.features.migration.migration_task import MigrationTaskModel
from src.platform.jobs.task_model import TaskStatus
from tests.graphql.helpers import (
    GET_MIGRATION_TASKS,
    assert_no_errors,
)

pytestmark = pytest.mark.query


async def test_get_migration_tasks_empty(execute_gql, init_db):
    result = await execute_gql(GET_MIGRATION_TASKS, {
        "input": {}
    })
    assert_no_errors(result)
    data = result.data["getMigrationTasks"]
    assert data["totalCount"] == 0
    assert data["tasks"] == []
    assert data["page"] == 1


async def test_get_migration_tasks_returns_tasks(execute_gql, init_db):
    now = time.time()
    for i in range(3):
        task = MigrationTaskModel(
            source_path=f"Cat/Pseudo/file{i}.mp4",
            source_category="Cat",
            target_path=f"Cat2/Pseudo2/file{i}.mp4",
            target_category="Cat2",
            file_name=f"file{i}",
            file_size=100 * (i + 1),
            status=TaskStatus.PENDING,
            created_at=now + i,
            updated_at=now + i,
        )
        await task.insert()

    result = await execute_gql(GET_MIGRATION_TASKS, {
        "input": {"pageSize": 2, "page": 1}
    })
    assert_no_errors(result)
    data = result.data["getMigrationTasks"]
    assert data["totalCount"] == 3
    assert len(data["tasks"]) == 2
    assert data["pageSize"] == 2


async def test_get_migration_tasks_status_filter(execute_gql, init_db):
    now = time.time()
    for status in (TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.FAILED):
        task = MigrationTaskModel(
            source_path=f"Cat/Pseudo/{status}.mp4",
            source_category="Cat",
            target_path=f"Cat2/Pseudo2/{status}.mp4",
            target_category="Cat2",
            file_name=status,
            file_size=100,
            status=status,
            created_at=now,
            updated_at=now,
        )
        await task.insert()

    result = await execute_gql(GET_MIGRATION_TASKS, {
        "input": {"statusFilter": ["PENDING", "FAILED"]}
    })
    assert_no_errors(result)
    data = result.data["getMigrationTasks"]
    assert data["totalCount"] == 2
    statuses = {t["status"] for t in data["tasks"]}
    assert statuses == {"PENDING", "FAILED"}


async def test_get_migration_tasks_pagination(execute_gql, init_db):
    now = time.time()
    for i in range(5):
        task = MigrationTaskModel(
            source_path=f"Cat/Pseudo/f{i}.mp4",
            source_category="Cat",
            target_path=f"Cat2/Pseudo2/f{i}.mp4",
            target_category="Cat2",
            file_name=f"f{i}",
            file_size=100,
            status=TaskStatus.PENDING,
            created_at=now + i,
            updated_at=now + i,
        )
        await task.insert()

    result = await execute_gql(GET_MIGRATION_TASKS, {
        "input": {"page": 2, "pageSize": 2}
    })
    assert_no_errors(result)
    data = result.data["getMigrationTasks"]
    assert data["totalCount"] == 5
    assert data["page"] == 2
    assert len(data["tasks"]) == 2
