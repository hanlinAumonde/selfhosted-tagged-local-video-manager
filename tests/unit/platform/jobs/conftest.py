import time

import pytest_asyncio
from beanie import init_beanie

from src.features.migration.migration_task import MigrationTaskModel
from src.platform.jobs.task_model import TaskStatus
from tests.unit.platform.jobs.reindex import ReindexTaskModel


@pytest_asyncio.fixture
async def reindex_db(init_db):
    """Register the test-only task model against the same test database."""
    database = MigrationTaskModel.get_pymongo_collection().database
    await init_beanie(database=database, document_models=[ReindexTaskModel])
    yield
    await ReindexTaskModel.delete_all()


@pytest_asyncio.fixture
def reindex_task_factory(reindex_db):
    async def _create(**kwargs) -> ReindexTaskModel:
        now = time.time()
        defaults = {
            "documents_total": 10,
            "status": TaskStatus.PENDING,
            "created_at": now,
            "updated_at": now,
        }
        defaults.update(kwargs)
        task = ReindexTaskModel(**defaults)
        await task.insert()
        return task
    return _create

