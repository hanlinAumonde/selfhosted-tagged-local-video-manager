"""GraphQL-specific fixtures.

This conftest:
- Auto-marks every test under tests/graphql/ with the ``graphql`` marker.
- Provides ``execute_gql`` / ``subscribe_gql`` helpers that drive
  ``schema.execute`` / ``schema.subscribe`` directly (no HTTP layer).
- Provides spec'd Mock objects for every service that touches the filesystem
  (resource handler, ffmpeg, thumbnail, dir_metadata, browse_file,
  batch_operation).  Pure-DB services (TagOperationService, SeriesService,
  CacheService) are kept real so the tests still exercise the business logic.
"""

from collections.abc import AsyncGenerator
from contextlib import contextmanager
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from src.config import Settings
from src.context import ContextEnum
from src.features.migration.migration_task import TaskStatus
from src.schema.strawberry_schema import schema as gql_schema
from src.features.browsing.batch_operation_service import BatchOperationService
from src.features.browsing.browse_file_service import BrowseFileService
from src.platform.cache.cache_service import CacheService
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.media.ffmpeg_service import FFmpegService
from src.features.migration.migration_service import MIGRATION_EXECUTOR_KEY, MigrationService
from src.platform.jobs.path_locks import PathLockRegistry
from src.platform.jobs.task_runner import TaskRunner
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.features.catalog.catalog_service import CatalogService
from src.features.catalog.series_service import SeriesService
from src.features.catalog.tag_operation_service import TagOperationService
from src.features.playback.thumbnail_service import ThumbnailService


# -----------------------------------------------------------------------
# ----------------------- Auto-apply graphql mark ------------------------
# -----------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/graphql" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.graphql)


# -----------------------------------------------------------------------
# ---------------------------- Schema fixture ----------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def schema():
    return gql_schema


# -----------------------------------------------------------------------
# ----------------------- Filesystem-touching mocks ----------------------
# -----------------------------------------------------------------------

@pytest.fixture
def mock_handler() -> MagicMock:
    """A mock BaseResourceHandler with reasonable defaults for path conversion."""

    handler = MagicMock(name="ResourceHandler")
    # Identity-ish path conversions are good enough for resolvers that just
    # round-trip the string.  Tests that care about specific values can
    # override these.
    handler.convert_to_DB_format_path.side_effect = lambda p: p
    handler.convert_to_FS_format_path.side_effect = lambda p: p
    handler.get_path_standard_format.side_effect = lambda p: p
    handler.dirname.side_effect = lambda p: p.rsplit("/", 1)[0] if "/" in p else ""
    handler.is_video_file.return_value = True
    handler.get_filename_without_extension.side_effect = (
        lambda name: name.rsplit(".", 1)[0]
    )
    handler.resolve_path.side_effect = lambda category, pseudo_name, sub_path: (
        category if pseudo_name is None else (
            f"{category}/{pseudo_name}" if not sub_path
            else f"{category}/{pseudo_name}{sub_path}"
        )
    )

    @contextmanager
    def _list_directory(path: str):
        yield iter([])
    handler.list_directory.side_effect = _list_directory
    return handler


@pytest.fixture
def mock_resource_handler_service(mock_handler, test_settings: Settings) -> MagicMock:
    svc = MagicMock(spec=ResourceHandlerService, name="ResourceHandlerService")
    svc.get_handler.return_value = mock_handler
    svc.get_all_categories.return_value = test_settings.get_valid_categories()
    svc.get_pseudo_names.side_effect = lambda cat: list(
        test_settings.resource_paths.get(cat, {}).keys()
    )
    return svc


@pytest.fixture
def mock_ffmpeg_service() -> MagicMock:
    svc = MagicMock(spec=FFmpegService, name="FFmpegService")
    svc.get_video_duration = AsyncMock(return_value=120.0)
    return svc


@pytest.fixture
def mock_thumbnail_service() -> MagicMock:
    return MagicMock(spec=ThumbnailService, name="ThumbnailService")


@pytest.fixture
def mock_dir_metadata_service() -> MagicMock:
    svc = MagicMock(spec=DirMetadataService, name="DirMetadataService")
    svc.calculate_directory_metadata = AsyncMock(return_value=(0.0, 0.0))
    svc.update_directory_metadata_forward = AsyncMock(return_value=None)
    svc.batch_update_metadata_forward = AsyncMock(return_value=None)
    svc.get_metadata = AsyncMock(return_value=None)
    svc.set_metadata = AsyncMock(return_value=None)
    svc.bulk_set_metadata = AsyncMock(return_value=None)
    return svc


@pytest.fixture
def mock_browse_file_service() -> MagicMock:
    svc = MagicMock(spec=BrowseFileService, name="BrowseFileService")
    svc.get_node_list_in_directory = AsyncMock(return_value=[])
    svc.get_all_video_entries_in_directory = MagicMock(return_value=[])
    svc.search_videos_in_directory = AsyncMock(return_value=[])
    svc.create_directory = AsyncMock(return_value="Test-category/Test-resource/new_folder")
    return svc


@pytest.fixture
def mock_batch_operation_service() -> MagicMock:
    """A MagicMock(spec=...) of BatchOperationService.

    By default, ``batch_update`` / ``batch_delete`` return empty async
    generators.  Tests can swap in their own generators to drive specific
    progress flows.  ``constructBatchOperationStatus`` is left as the real
    implementation since it's pure construction.
    """
    real = BatchOperationService.__new__(BatchOperationService)

    svc = MagicMock(spec=BatchOperationService, name="BatchOperationService")

    async def _empty(*_a, **_kw):
        if False:
            yield
    svc.batch_update.side_effect = _empty
    svc.batch_delete.side_effect = _empty
    svc.constructBatchOperationStatus = real.constructBatchOperationStatus
    return svc


@pytest.fixture
def mock_migration_service() -> MagicMock:
    svc = MagicMock(spec=MigrationService, name="MigrationService")
    # list_tasks is a plain query over the tasks collection and holds no service state,
    # so the real implementation is bound on: these tests assert against real documents.
    svc.list_tasks = MigrationService.list_tasks.__get__(svc, MigrationService)
    svc.is_file_locked = AsyncMock(return_value=False)
    svc.prepare_retry = AsyncMock(return_value=TaskStatus.PROCESSING)
    return svc


@pytest.fixture
def mock_task_runner() -> MagicMock:
    """By default the runner accepts submissions and observes nothing."""
    runner = MagicMock(spec=TaskRunner, name="TaskRunner")
    runner.submit = AsyncMock(return_value=None)

    async def _empty(*_a, **_kw):
        if False:
            yield
    runner.observe.side_effect = _empty
    return runner


# -----------------------------------------------------------------------
# ----------------------- Real (DB-backed) services ----------------------
# -----------------------------------------------------------------------

@pytest.fixture
def real_cache_service(test_settings: Settings) -> CacheService:
    return CacheService(config=test_settings.cache_config)


@pytest.fixture
def real_tag_operation_service(test_settings: Settings) -> TagOperationService:
    return TagOperationService(settings=test_settings)


@pytest.fixture
def real_series_service() -> SeriesService:
    return SeriesService()


@pytest.fixture
def real_path_lock_registry(
    mock_dir_metadata_service: MagicMock,
    mock_resource_handler_service: MagicMock,
) -> PathLockRegistry:
    """The registry as the composition root builds it: migration registered as a provider,
    so lock state still comes from real task documents."""
    registry = PathLockRegistry()
    registry.register(
        MIGRATION_EXECUTOR_KEY,
        MigrationService(
            resource_handler_service=mock_resource_handler_service,
            dir_metadata_service=mock_dir_metadata_service,
        ),
    )
    return registry


@pytest.fixture
def real_catalog_service(
    test_settings: Settings,
    real_tag_operation_service: TagOperationService,
    mock_dir_metadata_service: MagicMock,
    mock_resource_handler_service: MagicMock,
    mock_ffmpeg_service: MagicMock,
    real_path_lock_registry: PathLockRegistry,
) -> CatalogService:
    return CatalogService(
        settings=test_settings,
        tag_operation_service=real_tag_operation_service,
        dir_metadata_service=mock_dir_metadata_service,
        resource_handler_service=mock_resource_handler_service,
        ffmpeg_service=mock_ffmpeg_service,
        path_locks=real_path_lock_registry,
    )


# -----------------------------------------------------------------------
# --------------------------- Context fixture ---------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def graphql_context(
    test_settings: Settings,
    real_cache_service: CacheService,
    real_tag_operation_service: TagOperationService,
    real_series_service: SeriesService,
    real_catalog_service: CatalogService,
    mock_resource_handler_service: MagicMock,
    mock_ffmpeg_service: MagicMock,
    mock_thumbnail_service: MagicMock,
    mock_dir_metadata_service: MagicMock,
    mock_browse_file_service: MagicMock,
    mock_batch_operation_service: MagicMock,
    mock_migration_service: MagicMock,
    mock_task_runner: MagicMock,
) -> dict[ContextEnum, Any]:
    """Context dict matching ``src.context.get_context``'s return shape."""
    return {
        ContextEnum.SETTINGS: test_settings,
        ContextEnum.CACHE_SERVICE: real_cache_service,
        ContextEnum.RESOURCE_HANDLER_SERVICE: mock_resource_handler_service,
        ContextEnum.FFMPEG_SERVICE: mock_ffmpeg_service,
        ContextEnum.THUMBNAIL_SERVICE: mock_thumbnail_service,
        ContextEnum.TAG_OPERATION_SERVICE: real_tag_operation_service,
        ContextEnum.SERIES_SERVICE: real_series_service,
        ContextEnum.DIR_METADATA_SERVICE: mock_dir_metadata_service,
        ContextEnum.BROWSE_FILE_SERVICE: mock_browse_file_service,
        ContextEnum.BATCH_OPERATION_SERVICE: mock_batch_operation_service,
        ContextEnum.CATALOG_SERVICE: real_catalog_service,
        ContextEnum.MIGRATION_SERVICE: mock_migration_service,
        ContextEnum.TASK_RUNNER: mock_task_runner,
    }


# -----------------------------------------------------------------------
# --------------------------- Execute helpers ---------------------------
# -----------------------------------------------------------------------

@pytest_asyncio.fixture
def execute_gql(graphql_context, schema) -> Callable:
    """Run a GraphQL document via ``schema.execute`` against the test context.

    Usage::

        result = await execute_gql(QUERY, {"input": {...}})
        assert result.errors is None
        assert result.data["getVideoById"]["id"] == "..."
    """

    async def _execute(query: str, variables: dict | None = None):
        return await schema.execute(
            query,
            variable_values=variables,
            context_value=graphql_context,
        )

    return _execute


@pytest_asyncio.fixture
def subscribe_gql(graphql_context, schema) -> Callable:
    """Run a GraphQL subscription and collect every yielded payload.

    Returns a list of ExecutionResult-like objects (one per event).
    """

    async def _subscribe(query: str, variables: dict | None = None) -> list:
        events: list = []
        result = await schema.subscribe(
            query,
            variable_values=variables,
            context_value=graphql_context,
        )
        # On validation errors, schema.subscribe returns a single
        # ExecutionResult, not an async iterator.
        if isinstance(result, AsyncGenerator) or hasattr(result, "__aiter__"):
            async for event in result:
                events.append(event)
        else:
            events.append(result)
        return events

    return _subscribe
