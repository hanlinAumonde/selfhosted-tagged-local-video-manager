"""Startup wiring for the task runner.

``init_task_runner`` resolves the service graph by hand because the app lifespan runs
outside FastAPI's Depends() machinery — worth pinning down, since a mistake there only
shows up at boot.
"""

import pytest

from src import context as context_module
from src.context import ContextEnum, init_task_runner
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus
from src.features.migration.migration_service import MigrationService

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_context_singletons():
    """The context module memoises services in globals; keep tests isolated."""
    names = [
        "_cache_service", "_resource_handler_service", "_ffmpeg_service",
        "_tag_operation_service", "_series_service", "_migration_service",
        "_task_runner",
    ]
    saved = {n: getattr(context_module, n) for n in names}
    for n in names:
        setattr(context_module, n, None)
    yield
    for n, value in saved.items():
        setattr(context_module, n, value)


async def test_bootstrap_wires_and_starts_the_runner(two_category_settings, init_db):
    runner = await init_task_runner()
    try:
        assert runner._workers, "workers should be running after startup"
        assert len(runner._workers) == two_category_settings.tasks.max_concurrent

        executor = runner._executors["migration"]
        assert isinstance(executor, MigrationService)
        # The same instance must come back through request-scoped DI.
        assert context_module._migration_service is executor
        assert executor._progress_flush_interval == two_category_settings.tasks.progress_flush_interval
    finally:
        await runner.shutdown()

    assert not runner._workers


async def test_bootstrap_recovers_orphaned_tasks(two_category_settings, init_db, task_factory):
    """A task left PROCESSING by a dead process is picked back up at boot."""
    orphan = await task_factory(status=TaskStatus.DB_UPDATED)

    runner = await init_task_runner()
    try:
        refreshed = await MigrationTaskModel.get(orphan.id)
        # plan_recovery resets it to PENDING and re-queues it.
        assert refreshed.status in (TaskStatus.PENDING, TaskStatus.DELETING_SOURCE,
                                    TaskStatus.COMPLETED, TaskStatus.FAILED)
        assert refreshed.status != TaskStatus.DB_UPDATED
    finally:
        await runner.shutdown()


async def test_context_exposes_the_runner(two_category_settings, init_db):
    runner = await init_task_runner()
    try:
        assert ContextEnum.TASK_RUNNER.value is type(runner)
    finally:
        await runner.shutdown()
