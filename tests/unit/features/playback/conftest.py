from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Settings
from src.platform.storage.local_fs.local_fs_handler import LocalFSResourceHandler
from src.features.playback.thumbnail_service import ThumbnailService


def _mock_handler():
    h = MagicMock(spec=LocalFSResourceHandler, name="handler")
    h.convert_to_FS_format_path.side_effect = lambda p: p
    h.convert_to_DB_format_path.side_effect = lambda p: p
    h.get_path_standard_format.side_effect = lambda p: p
    h.get_ffmpeg_accessible_path.return_value = "/fake.mp4"
    h.file_exists.return_value = True
    h.get_filename_without_extension.side_effect = lambda n: n.rsplit(".", 1)[0]
    return h


@pytest.fixture
def handler():
    return _mock_handler()


@pytest.fixture
def handler_svc(handler):
    svc = MagicMock(name="ResourceHandlerService")
    svc.get_handler.return_value = handler
    return svc


@pytest.fixture
def ffmpeg_svc():
    svc = MagicMock(name="FFmpegService")
    svc.generate_thumbnail = AsyncMock(return_value=b"JPEG-DATA")
    svc.get_video_duration = AsyncMock(return_value=120.0)
    return svc


@pytest.fixture
def thumb_svc(handler_svc, ffmpeg_svc, test_settings: Settings) -> ThumbnailService:
    """ThumbnailService with no storage configured (on-the-fly generation)."""
    return ThumbnailService(
        resource_handler_service=handler_svc,
        ffmpeg_service=ffmpeg_svc,
        settings=test_settings,
    )


@pytest.fixture
def thumb_svc_with_storage(handler_svc, ffmpeg_svc, handler):
    """ThumbnailService with storage configured."""
    settings = Settings.model_validate({
        "resource_paths": {"Test-category": {"Test-resource": "/test"}},
        "thumbnail_config": {
            "storage_category": "Test-category",
            "storage_pseudo_name": "Test-resource",
        },
    })
    svc = ThumbnailService(
        resource_handler_service=handler_svc,
        ffmpeg_service=ffmpeg_svc,
        settings=settings,
    )

    storage = MagicMock(spec=LocalFSResourceHandler, name="storage_handler")
    storage.join_path.side_effect = lambda *parts: "/".join(parts)
    storage.file_exists.return_value = True
    storage.get_size.return_value = 1024
    storage.read_file_chunk = AsyncMock(return_value=b"STORED-JPEG")
    storage.write_file = AsyncMock()
    svc._storage_handler = storage
    return svc