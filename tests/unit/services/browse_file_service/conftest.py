
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Settings
from src.features.browsing.browse_file_service import BrowseFileService
from src.platform.cache.cache_service import CacheService
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.features.migration.migration_service import MIGRATION_EXECUTOR_KEY, MigrationService
from src.platform.jobs.path_locks import PathLockRegistry
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.resource_handler_service import ResourceHandlerService


@pytest.fixture
def dir_meta_svc(
    fs_settings: Settings,
    local_resource_handler_service: ResourceHandlerService,
    local_cache_service: CacheService,
) -> DirMetadataService:
    return DirMetadataService(
        settings=fs_settings,
        resource_handler_service=local_resource_handler_service,
        cache_service=local_cache_service,
    )


@pytest.fixture
def ffmpeg_svc() -> MagicMock:
    svc = MagicMock(spec=FFmpegService, name="FFmpegService")
    svc.get_video_duration = AsyncMock(return_value=120.0)
    return svc


@pytest.fixture
def migration_path_locks(
    dir_meta_svc: DirMetadataService,
    local_resource_handler_service: ResourceHandlerService,
) -> PathLockRegistry:
    """A registry wired to the real migration provider.

    Browsing itself no longer knows migration exists; the tests that are *about* migration
    targets still need the genuine provider behind the registry.
    """
    registry = PathLockRegistry()
    registry.register(
        MIGRATION_EXECUTOR_KEY,
        MigrationService(
            resource_handler_service=local_resource_handler_service,
            dir_metadata_service=dir_meta_svc,
        ),
    )
    return registry


@pytest.fixture
def browse_svc(
    fs_settings: Settings,
    dir_meta_svc: DirMetadataService,
    local_resource_handler_service: ResourceHandlerService,
    ffmpeg_svc: MagicMock,
    migration_path_locks: PathLockRegistry,
) -> BrowseFileService:
    return BrowseFileService(
        settings=fs_settings,
        dir_metadata_service=dir_meta_svc,
        resource_handler_service=local_resource_handler_service,
        ffmpegService=ffmpeg_svc,
        path_locks=migration_path_locks,
    )
