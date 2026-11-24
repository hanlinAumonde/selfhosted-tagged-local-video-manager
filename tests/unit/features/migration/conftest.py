import errno
import os
from pathlib import Path

import pytest

from src.config import Settings
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.features.catalog.series_service import SeriesService
from src.features.migration.device_slots import DeviceSlots
from src.features.migration.migration_batch import MigrationBatchService
from src.features.migration.migration_service import MigrationService
from tests.unit.features.migration.batch_helpers import record_directory_refreshes
from src.platform.redis.redis_cache import RedisCache
from src.platform.storage.resource_handler_service import ResourceHandlerService


@pytest.fixture
def no_hard_links(monkeypatch) -> None:
    """A filesystem such as exFAT, which refuses every hard link."""

    def refuse(src, dst, **kwargs):
        raise OSError(errno.EPERM, "Incorrect function")

    monkeypatch.setattr(os, "link", refuse)


@pytest.fixture
def shelf(local_resource_dir: Path) -> Path:
    directory = local_resource_dir / "shelf"
    directory.mkdir()
    return directory


@pytest.fixture
async def shelving_task(video_factory, task_factory, shelf):
    """A PENDING migration between two directories of one mount."""
    source = "Test-category/Test-resource/movie_a.mp4"
    await video_factory(name="movie_a", path=source)
    return await task_factory(
        source_path=source,
        target_path="Test-category/Test-resource/shelf/movie_a.mp4",
        target_category="Test-category",
    )


@pytest.fixture
def migration_svc(
    fs_settings: Settings,
    local_resource_handler_service: ResourceHandlerService,
    redis_cache: RedisCache,
) -> MigrationService:
    dir_meta = DirMetadataService(
        settings=fs_settings,
        resource_handler_service=local_resource_handler_service,
        cache=redis_cache,
    )
    return MigrationService(
        resource_handler_service=local_resource_handler_service,
        dir_metadata_service=dir_meta,
        series_service=SeriesService(),
    )


@pytest.fixture
def slotted_migration_svc(
    two_category_settings: Settings,
    two_cat_handler_service: ResourceHandlerService,
    redis_cache: RedisCache,
) -> MigrationService:
    dir_meta = DirMetadataService(
        settings=two_category_settings,
        resource_handler_service=two_cat_handler_service,
        cache=redis_cache,
    )
    return MigrationService(
        resource_handler_service=two_cat_handler_service,
        dir_metadata_service=dir_meta,
        series_service=SeriesService(),
        copy_slots=DeviceSlots.from_settings(two_category_settings),
    )


@pytest.fixture
def two_cat_migration_svc(
    two_category_settings: Settings,
    two_cat_handler_service: ResourceHandlerService,
    redis_cache: RedisCache,
) -> MigrationService:
    dir_meta = DirMetadataService(
        settings=two_category_settings,
        resource_handler_service=two_cat_handler_service,
        cache=redis_cache,
    )
    return MigrationService(
        resource_handler_service=two_cat_handler_service,
        dir_metadata_service=dir_meta,
        series_service=SeriesService(),
    )


@pytest.fixture
def batch_svc(two_cat_migration_svc: MigrationService) -> MigrationBatchService:
    return MigrationBatchService(two_cat_migration_svc)


@pytest.fixture
def refreshed_dirs(two_cat_migration_svc: MigrationService) -> list[tuple[str, str]]:
    """Records every directory whose metadata is refreshed, as ``(category, DB path)``,
    while still letting the real refresh run."""
    return record_directory_refreshes(two_cat_migration_svc)
