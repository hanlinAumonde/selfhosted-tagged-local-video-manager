from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import StreamingResponse

from src.config import Settings
from src.platform.storage.file_info import FileInfo
from src.platform.storage.local_fs.local_fs_handler import LocalFSResourceHandler
from src.features.playback.thumbnail_service import StorageBreaker, ThumbnailService


def _mock_handler():
    h = MagicMock(spec=LocalFSResourceHandler, name="handler")
    h.convert_to_FS_format_path.side_effect = lambda p: p
    h.convert_to_DB_format_path.side_effect = lambda p: p
    h.get_path_standard_format.side_effect = lambda p: p
    h.get_ffmpeg_accessible_path.return_value = "/fake.mp4"
    h.stat.return_value = FileInfo(name="video.mp4", path="/video.mp4", is_dir=False, size=1024, mtime=1.0)
    h.get_filename_without_extension.side_effect = lambda n: n.rsplit(".", 1)[0]
    return h


class FakeClock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


STORAGE_COOLDOWN = 30.0


async def run_attached_work(response: StreamingResponse) -> None:
    """Run what the server would run once the response has been sent."""
    if response.background is not None:
        await response.background()


async def body_of(response: StreamingResponse) -> bytes:
    chunks = [chunk async for chunk in response.body_iterator]
    return b"".join(chunks)


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
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def storage_breaker(clock) -> StorageBreaker:
    return StorageBreaker(cooldown=STORAGE_COOLDOWN, clock=clock)


@pytest.fixture
def thumb_svc(handler_svc, ffmpeg_svc, storage_breaker, test_settings: Settings) -> ThumbnailService:
    """ThumbnailService with no storage configured (on-the-fly generation)."""
    return ThumbnailService(
        resource_handler_service=handler_svc,
        ffmpeg_service=ffmpeg_svc,
        settings=test_settings,
        storage_breaker=storage_breaker,
    )


@pytest.fixture
def thumb_svc_with_storage(handler_svc, ffmpeg_svc, storage_breaker, handler):
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
        storage_breaker=storage_breaker,
    )

    storage = MagicMock(spec=LocalFSResourceHandler, name="storage_handler")
    storage.join_path.side_effect = lambda *parts: "/".join(parts)
    storage.read_file.return_value = b"STORED-JPEG"
    storage.write_file = AsyncMock()
    svc._storage_handler = storage
    return svc
