from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Settings
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.features.catalog.catalog_service import CatalogService
from src.features.catalog.tag_operation_service import TagOperationService
from src.platform.cache.cache_service import CacheService
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.resource_handler_service import ResourceHandlerService


@pytest.fixture
def catalog_svc_factory(
    fs_settings: Settings,
    local_resource_handler_service: ResourceHandlerService,
    local_cache_service: CacheService,
):
    """Build a catalog service around a given lock registry."""
    def _build(registry) -> CatalogService:
        ffmpeg = MagicMock(spec=FFmpegService, name="FFmpegService")
        ffmpeg.get_video_duration = AsyncMock(return_value=120.0)
        return CatalogService(
            settings=fs_settings,
            tag_operation_service=TagOperationService(settings=fs_settings),
            dir_metadata_service=DirMetadataService(
                settings=fs_settings,
                resource_handler_service=local_resource_handler_service,
                cache_service=local_cache_service,
            ),
            resource_handler_service=local_resource_handler_service,
            ffmpeg_service=ffmpeg,
            path_locks=registry,
        )
    return _build
