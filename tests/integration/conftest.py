"""Integration test fixtures.

Wires up ALL real services (except FFmpegService) against a real filesystem
(tmp_path) and real MongoDB (testcontainer), then drives the GraphQL schema
directly.  This exercises the full stack:
  GraphQL API -> resolvers -> services -> database + filesystem
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from src import config
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
from src.features.migration.migration_service import MIGRATION_EXECUTOR_KEY, MigrationService
from src.platform.jobs.path_locks import PathLockRegistry
from src.features.catalog.tag_operation_service import TagOperationService
from src.features.playback.thumbnail_service import ThumbnailService


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
    monkeypatch,
) -> Settings:
    payload = test_settings.model_dump()
    payload["resource_paths"] = {
        "Test-category": {"Test-resource": str(integration_resource_dir)},
    }
    settings = Settings.model_validate(payload)
    monkeypatch.setattr(config, "_settings", settings)
    return settings


# -----------------------------------------------------------------------
# ----------------------- Real services ---------------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def real_resource_handler_service(integration_settings: Settings) -> ResourceHandlerService:
    return ResourceHandlerService(settings=integration_settings)


@pytest.fixture
def real_cache_service(integration_settings: Settings) -> CacheService:
    return CacheService(config=integration_settings.cache_config)


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
def real_path_lock_registry(
    real_dir_metadata_service: DirMetadataService,
    real_resource_handler_service: ResourceHandlerService,
) -> PathLockRegistry:
    """The registry as the composition root builds it: migration registered as a provider,
    so lock state still comes from real task documents."""
    registry = PathLockRegistry()
    registry.register(
        MIGRATION_EXECUTOR_KEY,
        MigrationService(
            resource_handler_service=real_resource_handler_service,
            dir_metadata_service=real_dir_metadata_service,
        ),
    )
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
    )


# -----------------------------------------------------------------------
# ----------------------- Mock migration service ---------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def mock_migration_service() -> MagicMock:
    svc = MagicMock(spec=MigrationService, name="MigrationService")
    svc.is_file_locked = AsyncMock(return_value=False)
    return svc


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
    mock_migration_service: MagicMock,
) -> dict[ContextEnum, Any]:
    return {
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
        ContextEnum.MIGRATION_SERVICE: mock_migration_service,
    }


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