"""Migration journeys need a second category to move into, and someone to play the worker.

The worker is the real ``MigrationWorker`` — the object the worker process builds — run on
the same Mongo, Redis and queue as the web side. Instead of a taskiq process consuming the
queue, a test calls ``drain_queue()``, which runs every task id the web side (and the
worker's own batch hand-offs) put on the queue, in the order they were put there.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from src.config import Settings
from src.workers.worker_migration import MigrationWorker
from tests.broker_helpers import RecordingBroker
from tests.integration.graphql_documents import CREATE_MIGRATION_TASK
from tests.integration.helpers import assert_no_errors, build_integration_settings

SOURCE_DIR = "Test-category/Test-resource"
TARGET_DIR = "Target-category/Target-resource"

# Far more deliveries than any journey here makes; reaching it means the worker keeps
# handing the queue work that never finishes.
_MAX_DELIVERIES = 50

#: How long a subscription test waits for its stream to end.
SUBSCRIPTION_TIMEOUT = 10
_WATCHDOG_INTERVAL = 60


@pytest.fixture
def target_resource_dir(tmp_path: Path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    return target


@pytest.fixture
def integration_settings(
    test_settings: Settings,
    integration_resource_dir: Path,
    target_resource_dir: Path,
    redis_url: str,
    monkeypatch,
) -> Settings:
    # Two categories, so a migration crosses handlers and streams its bytes like a move
    # between two mounts does.
    settings = build_integration_settings(
        test_settings,
        {
            "Test-category": {"Test-resource": str(integration_resource_dir)},
            "Target-category": {"Target-resource": str(target_resource_dir)},
        },
        redis_url,
        monkeypatch,
    )
    # The bus's watchdog ends a subscription from the stored status when no frame arrives,
    # which would let a subscription test pass with the worker's frames never reaching
    # the web side. Push it past every subscription timeout here.
    settings.tasks.observe_watchdog_interval = _WATCHDOG_INTERVAL
    return settings


@pytest_asyncio.fixture
async def migration_worker(
    integration_settings: Settings, migration_broker: RecordingBroker, redis: Redis, init_db
) -> AsyncGenerator[MigrationWorker, None]:
    worker = MigrationWorker(integration_settings, migration_broker, redis)
    yield worker
    await worker.stop()
    await worker.cache_service.close()


@pytest.fixture
def drain_queue(
    migration_worker: MigrationWorker, migration_broker: RecordingBroker
) -> Callable[[], Awaitable[None]]:
    async def _drain() -> None:
        for _ in range(_MAX_DELIVERIES):
            if not migration_broker.delivered:
                return
            await migration_worker.run(migration_broker.delivered.pop(0))
        raise AssertionError(f"queue still not empty after {_MAX_DELIVERIES} deliveries")

    return _drain


@pytest.fixture
def create_migration(execute_gql) -> Callable[..., Awaitable[str]]:
    """Create one migration to the target directory through GraphQL; returns the task id."""
    async def _create(video_id: str, target_dir: str = TARGET_DIR) -> str:
        result = await execute_gql(CREATE_MIGRATION_TASK, {"input": {
            "sourceVideoId": video_id,
            "targetDirRelativePath": {"relativePath": target_dir},
        }})
        assert_no_errors(result)
        assert result.data["createMigrationTask"]["success"] is True
        return result.data["createMigrationTask"]["task"]["id"]

    return _create
