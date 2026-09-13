from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Settings
from src.features.browsing.batch_operation_service import BatchOperationService
from src.features.browsing.browse_file_service import BrowseFileService
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.features.catalog.tag_operation_service import TagOperationService
from src.features.migration.migration_service import MIGRATION_EXECUTOR_KEY, MigrationService
from src.platform.cache.cache_service import CacheService
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
def dir_svc(dir_meta_svc: DirMetadataService) -> DirMetadataService:
    """The same service under its own tests' name.

    `dir_meta_svc` reads as a collaborator where browsing is the subject; `dir_svc` reads as
    the subject in the dir-metadata tests. One implementation, so the two can never drift.
    """
    return dir_meta_svc


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


@pytest.fixture
def mock_ffmpeg():
    svc = MagicMock(name="FFmpegService")
    svc.get_video_duration = AsyncMock(return_value=120.0)
    return svc


@pytest.fixture
def mock_thumbnail():
    return MagicMock(name="ThumbnailService")


@pytest.fixture
def batch_svc(
    fs_settings: Settings,
    local_resource_handler_service: ResourceHandlerService,
    dir_meta_svc: DirMetadataService,
    mock_ffmpeg,
    mock_thumbnail,
) -> BatchOperationService:
    return BatchOperationService(
        dir_metadata_service=dir_meta_svc,
        tag_operation_service=TagOperationService(settings=fs_settings),
        thumbnail_service=mock_thumbnail,
        resource_handler_service=local_resource_handler_service,
        ffmpeg_service=mock_ffmpeg,
    )
