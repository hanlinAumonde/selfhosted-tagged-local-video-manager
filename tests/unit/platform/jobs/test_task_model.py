"""
Behavioural constraints on BaseTaskModel and Beanie document inheritance.

These tests pin down the foundation the task template is generalised on: generic task
fields must belong to the base, migration-specific fields must stay on the subclass, and
inheritance must neither change collection ownership nor require migrating stored data.
"""

import pytest

from src.features.migration.migration_task import MigrationTaskModel
from src.platform.jobs.task_model import BaseTaskModel, TaskStatus

pytestmark = pytest.mark.unit


async def test_migration_task_model_inherits_base_task_model():
    assert issubclass(MigrationTaskModel, BaseTaskModel)


async def test_generic_task_fields_live_on_the_base_model():
    """Status, error and timestamps hold for every task type, so the base owns them."""
    for field in (
        "status",
        "error_message",
        "failed_step",
        "created_at",
        "updated_at",
        "completed_at",
    ):
        assert field in BaseTaskModel.model_fields, f"{field} should be declared by BaseTaskModel"


async def test_migration_specific_fields_stay_off_the_base_model():
    """Source/target paths and conflict strategy are migration's own; leaking them into
    the base would pollute every other task type."""
    for field in (
        "source_path",
        "source_category",
        "target_path",
        "target_category",
        "file_name",
        "file_size",
        "bytes_transferred",
        "conflict_strategy",
        "renamed_target_path",
    ):
        assert field not in BaseTaskModel.model_fields, f"{field} does not belong on BaseTaskModel"
        assert field in MigrationTaskModel.model_fields


async def test_subclass_keeps_its_own_collection(task_factory):
    """Inheritance must not move the collection — existing migration_tasks documents have
    to stay readable in place."""
    task = await task_factory()

    assert MigrationTaskModel.get_settings().name == "migration_tasks"
    raw = await MigrationTaskModel.get_pymongo_collection().find_one({"_id": task.id})
    assert raw is not None


async def test_base_task_model_does_not_create_a_collection_of_its_own(task_factory):
    """The base is a template only. It is never passed to init_beanie, so it must not
    leave a collection behind."""
    await task_factory()

    database = MigrationTaskModel.get_pymongo_collection().database
    collection_names = await database.list_collection_names()

    assert "BaseTaskModel" not in collection_names
    assert "base_tasks" not in collection_names


async def test_progress_accessors_map_onto_the_migration_byte_fields(task_factory):
    """Generic progress access maps onto migration's existing byte fields rather than
    introducing a parallel set."""
    task = await task_factory(file_size=100, bytes_transferred=0)

    assert task.get_progress() == (0, 100)

    task.set_progress(40)

    assert task.bytes_transferred == 40
    assert task.get_progress() == (40, 100)


async def test_progress_accessors_add_no_new_persisted_fields(task_factory):
    """Guards the zero-data-migration constraint: bytes_transferred remains the only
    progress field that reaches the database."""
    task = await task_factory(file_size=100)

    task.set_progress(40)
    await task.save()

    raw = await MigrationTaskModel.get_pymongo_collection().find_one({"_id": task.id})
    assert raw["bytes_transferred"] == 40
    assert "progress_current" not in raw
    assert "progress_total" not in raw


async def test_task_status_is_reachable_from_the_jobs_package():
    """The status enum moves up with the base so non-migration task types can use it."""
    assert TaskStatus.PENDING == "PENDING"
    assert TaskStatus.COMPLETED == "COMPLETED"
