"""Integration test fixtures.

Wires up ALL real services (except ffmpeg and thumbnail generation) against a real
filesystem (tmp_path), a real MongoDB and a real Redis (testcontainers), then drives the
GraphQL schema directly.  This exercises the full stack:
  GraphQL API -> resolvers -> services -> database + filesystem + task queue + progress
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from src.config import Settings
from src.context import ContextEnum
from src.schema.strawberry_schema import schema as gql_schema
from src.features.browsing.batch_operation_service import BatchOperationService
from src.features.browsing.browse_file_service import BrowseFileService
from src.platform.cache.cache_service import CacheService
from src.features.catalog.catalog_service import CatalogService
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.features.catalog.series_service import SeriesService
from src.features.migration.migration_batch import MigrationBatchService
from src.constants.tasks import MIGRATION_EXECUTOR_KEY
from src.features.migration.migration_service import MigrationService
from src.features.migration.migration_task import MigrationTaskModel
from src.workers.dispatch import TaskDispatcher
from src.platform.jobs.path_locks import PathLockRegistry
from src.platform.jobs.progress_bus import ProgressBus, ProgressPublisher
from src.features.catalog.tag_operation_service import TagOperationService
from src.features.playback.thumbnail_service import ThumbnailService
from tests.broker_helpers import RecordingBroker
from tests.integration.helpers import build_integration_settings


# -----------------------------------------------------------------------
# ----------------------- Auto-apply integration mark --------------------
# -----------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/integration" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


# -----------------------------------------------------------------------
# ----------------------- On-disk fixture tree ---------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def integration_resource_dir(tmp_path: Path) -> Path:
    """Build a realistic video tree for integration tests.

    Layout::

        <root>/
          alpha.mp4         (1000 bytes)
          beta.mp4          (2000 bytes)
          drama/
            charlie.mp4     (3000 bytes)
            delta.mp4       (4000 bytes)
          empty_dir/
    """
    root = tmp_path / "videos"
    root.mkdir()
    (root / "alpha.mp4").write_bytes(b"a" * 1000)
    (root / "beta.mp4").write_bytes(b"b" * 2000)
    drama = root / "drama"
    drama.mkdir()
    (drama / "charlie.mp4").write_bytes(b"c" * 3000)
    (drama / "delta.mp4").write_bytes(b"d" * 4000)
    (root / "empty_dir").mkdir()
    return root


# -----------------------------------------------------------------------
# ----------------------- Settings overrides -----------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def integration_settings(
    test_settings: Settings,
    integration_resource_dir: Path,
    redis_url: str,
    monkeypatch,
) -> Settings:
    return build_integration_settings(
        test_settings,
        {"Test-category": {"Test-resource": str(integration_resource_dir)}},
        redis_url,
        monkeypatch,
    )


# -----------------------------------------------------------------------
# ----------------------- Real services ---------------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def real_resource_handler_service(integration_settings: Settings) -> ResourceHandlerService:
    return ResourceHandlerService(settings=integration_settings)


@pytest_asyncio.fixture
async def real_cache_service(integration_settings: Settings) -> AsyncGenerator[CacheService, None]:
    cache = CacheService(config=integration_settings.cache_config)
    yield cache
    await cache.close()


@pytest.fixture
def mock_ffmpeg_service() -> MagicMock:
    svc = MagicMock(spec=FFmpegService, name="FFmpegService")
    svc.get_video_duration = AsyncMock(return_value=120.0)
    svc.generate_thumbnail = AsyncMock(return_value=b"\xff\xd8thumbnail")
    return svc


@pytest.fixture
def real_tag_operation_service(integration_settings: Settings) -> TagOperationService:
    return TagOperationService(settings=integration_settings)


@pytest.fixture
def real_series_service() -> SeriesService:
    return SeriesService()


@pytest.fixture
def real_dir_metadata_service(
    integration_settings: Settings,
    real_resource_handler_service: ResourceHandlerService,
    real_cache_service: CacheService,
) -> DirMetadataService:
    return DirMetadataService(
        settings=integration_settings,
        resource_handler_service=real_resource_handler_service,
        cache_service=real_cache_service,
    )


@pytest.fixture
def mock_thumbnail_service() -> MagicMock:
    return MagicMock(spec=ThumbnailService, name="ThumbnailService")


@pytest.fixture
def real_migration_service(
    integration_settings: Settings,
    real_resource_handler_service: ResourceHandlerService,
    real_dir_metadata_service: DirMetadataService,
    real_series_service: SeriesService,
) -> MigrationService:
    """The web side's migration service: creates, lists, cancels and retries tasks but
    holds no copy slots, because the worker is the one that runs them."""
    return MigrationService(
        resource_handler_service=real_resource_handler_service,
        dir_metadata_service=real_dir_metadata_service,
        series_service=real_series_service,
        progress_flush_interval=integration_settings.tasks.progress_flush_interval,
    )


@pytest.fixture
def real_path_lock_registry(real_migration_service: MigrationService) -> PathLockRegistry:
    """The registry as the composition root builds it: the same migration service the
    resolvers use is the provider, so lock state comes from real task documents."""
    registry = PathLockRegistry()
    registry.register(MIGRATION_EXECUTOR_KEY, real_migration_service)
    return registry


@pytest.fixture
def real_browse_file_service(
    integration_settings: Settings,
    real_dir_metadata_service: DirMetadataService,
    real_resource_handler_service: ResourceHandlerService,
    mock_ffmpeg_service: MagicMock,
    real_path_lock_registry: PathLockRegistry,
) -> BrowseFileService:
    return BrowseFileService(
        settings=integration_settings,
        dir_metadata_service=real_dir_metadata_service,
        resource_handler_service=real_resource_handler_service,
        ffmpegService=mock_ffmpeg_service,
        path_locks=real_path_lock_registry,
    )


@pytest.fixture
def real_batch_operation_service(
    real_dir_metadata_service: DirMetadataService,
    real_tag_operation_service: TagOperationService,
    mock_thumbnail_service: MagicMock,
    real_resource_handler_service: ResourceHandlerService,
    mock_ffmpeg_service: MagicMock,
) -> BatchOperationService:
    return BatchOperationService(
        dir_metadata_service=real_dir_metadata_service,
        tag_operation_service=real_tag_operation_service,
        thumbnail_service=mock_thumbnail_service,
        resource_handler_service=real_resource_handler_service,
        ffmpeg_service=mock_ffmpeg_service,
        series_service=SeriesService(),
    )


@pytest.fixture
def real_catalog_service(
    integration_settings: Settings,
    real_tag_operation_service: TagOperationService,
    real_dir_metadata_service: DirMetadataService,
    real_resource_handler_service: ResourceHandlerService,
    mock_ffmpeg_service: MagicMock,
    real_path_lock_registry: PathLockRegistry,
) -> CatalogService:
    return CatalogService(
        settings=integration_settings,
        tag_operation_service=real_tag_operation_service,
        dir_metadata_service=real_dir_metadata_service,
        resource_handler_service=real_resource_handler_service,
        ffmpeg_service=mock_ffmpeg_service,
        path_locks=real_path_lock_registry,
        series_service=SeriesService(),
    )


# -----------------------------------------------------------------------
# ----------------------- Task infrastructure ----------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def migration_broker() -> RecordingBroker:
    """The migration queue. Records the task ids it is handed instead of running them,
    so a test plays the worker by running what was delivered (see migration/conftest.py)."""
    return RecordingBroker()


@pytest_asyncio.fixture
async def redis(redis_url: str) -> AsyncGenerator[Redis, None]:
    client = Redis.from_url(redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def real_progress_bus(
    integration_settings: Settings, redis: Redis
) -> AsyncGenerator[ProgressBus, None]:
    bus = ProgressBus(
        redis,
        integration_settings.cache_config.key_prefix,
        watchdog_interval=integration_settings.tasks.observe_watchdog_interval,
    )
    await bus.start()
    yield bus
    await bus.stop()


# -----------------------------------------------------------------------
# ----------------------- GraphQL context --------------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def integration_context(
    integration_settings: Settings,
    real_cache_service: CacheService,
    real_resource_handler_service: ResourceHandlerService,
    mock_ffmpeg_service: MagicMock,
    mock_thumbnail_service: MagicMock,
    real_tag_operation_service: TagOperationService,
    real_series_service: SeriesService,
    real_dir_metadata_service: DirMetadataService,
    real_browse_file_service: BrowseFileService,
    real_batch_operation_service: BatchOperationService,
    real_catalog_service: CatalogService,
    real_migration_service: MigrationService,
    migration_broker: RecordingBroker,
    real_progress_bus: ProgressBus,
    redis: Redis,
) -> dict[ContextEnum, Any]:
    context = {
        ContextEnum.SETTINGS: integration_settings,
        ContextEnum.CACHE_SERVICE: real_cache_service,
        ContextEnum.RESOURCE_HANDLER_SERVICE: real_resource_handler_service,
        ContextEnum.FFMPEG_SERVICE: mock_ffmpeg_service,
        ContextEnum.THUMBNAIL_SERVICE: mock_thumbnail_service,
        ContextEnum.TAG_OPERATION_SERVICE: real_tag_operation_service,
        ContextEnum.SERIES_SERVICE: real_series_service,
        ContextEnum.DIR_METADATA_SERVICE: real_dir_metadata_service,
        ContextEnum.BROWSE_FILE_SERVICE: real_browse_file_service,
        ContextEnum.BATCH_OPERATION_SERVICE: real_batch_operation_service,
        ContextEnum.CATALOG_SERVICE: real_catalog_service,
        ContextEnum.MIGRATION_SERVICE: real_migration_service,
        ContextEnum.MIGRATION_BATCH_SERVICE: MigrationBatchService(real_migration_service),
        ContextEnum.MIGRATION_DISPATCHER: TaskDispatcher(migration_broker, MigrationTaskModel),
        ContextEnum.PROGRESS_BUS: real_progress_bus,
        ContextEnum.PROGRESS_PUBLISHER: ProgressPublisher(
            redis,
            integration_settings.cache_config.key_prefix,
            integration_settings.tasks.latest_frame_ttl,
        ),
    }
    # A key the composition root hands the resolvers but this context lacks would only
    # surface as a KeyError inside whichever resolver first asks for it.
    missing = set(ContextEnum) - context.keys()
    assert not missing, f"integration_context is missing {sorted(k.name for k in missing)}"
    return context


# -----------------------------------------------------------------------
# ----------------------- Execute helpers --------------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def schema():
    return gql_schema


@pytest_asyncio.fixture
def execute_gql(integration_context, schema) -> Callable:
    async def _execute(query: str, variables: dict | None = None):
        return await schema.execute(
            query,
            variable_values=variables,
            context_value=integration_context,
        )
    return _execute


@pytest_asyncio.fixture
def subscribe_gql(integration_context, schema) -> Callable:
    async def _subscribe(query: str, variables: dict | None = None) -> list:
        events: list = []
        result = await schema.subscribe(
            query,
            variable_values=variables,
            context_value=integration_context,
        )
        if isinstance(result, AsyncGenerator) or hasattr(result, "__aiter__"):
            async for event in result:
                events.append(event)
        else:
            events.append(result)
        return events
    return _subscribe


@pytest_asyncio.fixture
def stream_gql(integration_context, schema) -> Callable:
    """Open a subscription and hand back its event stream, for a test that has to act
    between events — e.g. start the worker only once the subscription has opened."""
    async def _stream(query: str, variables: dict | None = None):
        result = await schema.subscribe(
            query,
            variable_values=variables,
            context_value=integration_context,
        )
        assert hasattr(result, "__aiter__"), f"subscription did not open: {result}"
        return result
    return _stream