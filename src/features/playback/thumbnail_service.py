import io
import time
from typing import Callable

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from src.config import Settings
from src.features.catalog.video import VideoModel
from src.logger import get_logger
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.base_resource_handler import BaseResourceHandler
from src.platform.storage.resource_handler_service import ResourceHandlerService

logger = get_logger("thumbnail_service")


class StorageBreaker:
    """
    Stops talking to the thumbnail storage for a while after it fails.

    An unreachable S3 does not fail fast: each call waits out the connect timeout and
    the client's retries, and a page of thumbnails would pay that once per image —
    making on-the-fly generation far slower than when storage is merely empty. After a
    failure, storage is skipped for ``cooldown`` seconds; then exactly one call is let
    through to find out whether it is back, so a still-dead storage costs one timeout
    per cooldown rather than one per waiting request.

    It must outlive a request, which is why the composition root keeps a single
    ThumbnailService for the whole process rather than one per request.
    """

    def __init__(self, cooldown: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self._cooldown = cooldown
        self._clock = clock
        self._opened_at: float | None = None
        self._probing = False

    def allows(self) -> bool:
        if self._opened_at is None:
            return True
        if self._probing or self._clock() - self._opened_at < self._cooldown:
            return False
        self._probing = True
        return True

    def succeeded(self) -> None:
        self._opened_at = None
        self._probing = False

    def failed(self) -> None:
        self._opened_at = self._clock()
        self._probing = False


class ThumbnailService:
    def __init__(
        self,
        resource_handler_service: ResourceHandlerService,
        ffmpeg_service: FFmpegService,
        settings: Settings,
        storage_breaker: StorageBreaker | None = None,
    ):
        self.resourceHandlerService = resource_handler_service
        self.ffmpeg = ffmpeg_service
        self.settings = settings
        self._storage_breaker = storage_breaker or StorageBreaker()
        self._storage_handler = self._init_storage_handler()

    def _init_storage_handler(self) -> BaseResourceHandler | None:
        """
        Initialize the thumbnail storage handler based on config.
        Returns None if no storage is configured (thumbnails will be generated on-the-fly).

        :return: An instance of BaseResourceHandler for thumbnail storage, or None if not configured.
        :rtype: BaseResourceHandler | None
        """
        cfg = self.settings.thumbnail_config
        if not cfg.storage_category or not cfg.storage_pseudo_name:
            return None
        try:
            return self.resourceHandlerService.get_handler(cfg.storage_category)
        except ValueError:
            logger.warning(
                f"Thumbnail storage category '{cfg.storage_category}' not found. "
                "Thumbnails will be generated on-the-fly."
            )
            return None

    async def get_thumbnail(self, video_id: str) -> StreamingResponse:
        """
        Get the thumbnail image for a video. The method first tries to read a stored thumbnail if storage is configured,
        and falls back to generating a new thumbnail with ffmpeg if not found or if storage is not configured.

        :param video_id: The ID of the video to get the thumbnail for.
        :type video_id: str
        :return: A StreamingResponse containing the thumbnail image bytes.
        :rtype: StreamingResponse
        """            
        if not video_id:
            raise HTTPException(status_code=400, detail="Cannot find thumbnail without video-id")

        # 1- fetch video metadata from database
        video = await VideoModel.get(video_id)
        if not video:
            logger.warning(f"Video metadata not found for video_id: {video_id}")
            raise HTTPException(status_code=404, detail="Video not found")

        video_handler = self.resourceHandlerService.get_handler(video.category)
        video_path = AbsolutePath.from_existing_path(
            path=video.path, 
            category=video.category,
            handler=video_handler
        )
        video_fs_path = video_path.FS_format_path()
        if await video_handler.stat(video_fs_path) is None:
            logger.warning(f"Video file not found at path: {video_fs_path}")
            raise HTTPException(status_code=404, detail="Video file doesn't exist")

        # 2- try to read stored thumbnail (only if storage is configured)
        storage_path = (
            self._compute_thumbnail_storage_path(str(video.id))
            if self._storage_handler else None
        )
        if storage_path and video.thumbnail:
            if video.thumbnail == storage_path:
                if self._storage_breaker.allows():
                    thumbnail_bytes = await self._read_stored_thumbnail(video.thumbnail)
                    if thumbnail_bytes:
                        return self._build_thumbnail_response(thumbnail_bytes)
            else:
                # Legacy name-based key: it may be shared with a same-named video
                # living in another directory, so its content cannot be trusted.
                # Drop it and regenerate under the id-based key.
                logger.info(
                    f"Discarding legacy thumbnail key '{video.thumbnail}' for video "
                    f"{video.id}; regenerating at '{storage_path}'"
                )

        # 3- generate thumbnail with ffmpeg
        thumbnail_bytes = await self.ffmpeg.generate_thumbnail(video_handler, video_fs_path)

        # 4- answer now; storing it and probing a missing duration happen after the
        # response is sent. Neither changes what the client receives, and both can be
        # slow (an upload, another ffmpeg run), so the image should not wait on them.
        needs_duration = not video.duration
        if not storage_path and not needs_duration:
            return self._build_thumbnail_response(thumbnail_bytes)
        return self._build_thumbnail_response(
            thumbnail_bytes,
            background=BackgroundTask(
                self._persist_generated,
                video, video_handler, video_fs_path, storage_path, thumbnail_bytes, needs_duration,
            ),
        )

    async def _persist_generated(
        self,
        video: VideoModel,
        video_handler: BaseResourceHandler,
        video_fs_path: str,
        storage_path: str | None,
        thumbnail_bytes: bytes,
        needs_duration: bool,
    ) -> None:
        fields: dict[str, object] = {}
        if storage_path and await self._store_thumbnail(storage_path, thumbnail_bytes):
            # Only a key that was actually written may be recorded: a key pointing at
            # nothing makes every later request pay a storage miss before generating.
            fields["thumbnail"] = storage_path
        if needs_duration:
            fields["duration"] = await self.ffmpeg.get_video_duration(video_handler, video_fs_path)
        if fields:
            # $set just these fields: the document may have been edited since it was read.
            await video.set(fields)

    async def _read_stored_thumbnail(self, thumbnail_path: str) -> bytes | None:
        """
        :return: The stored bytes, or None when nothing is stored there or storage failed.
        """
        try:
            data = await self._storage_handler.read_file(thumbnail_path)
        except Exception as e:
            logger.warning(f"Failed to read stored thumbnail at {thumbnail_path}: {e}")
            self._storage_breaker.failed()
            return None
        # A missing object is a reachable storage answering: it says nothing about an outage.
        self._storage_breaker.succeeded()
        return data

    async def _store_thumbnail(self, path: str, data: bytes) -> bool:
        """
        :return: Whether the thumbnail is now in storage.
        """
        if not self._storage_breaker.allows():
            return False
        try:
            await self._storage_handler.write_file(path, data)
        except Exception as e:
            logger.warning(f"Failed to store thumbnail at {path}: {e}")
            self._storage_breaker.failed()
            return False
        self._storage_breaker.succeeded()
        return True

    def _compute_thumbnail_storage_path(self, video_id: str) -> str:
        """
        Compute the S3 key / storage path for a thumbnail.
        Format: thumbnails/{storage_pseudo_name}/{video_id}.jpg

        The video id is used instead of the file name because a file name is only
        unique inside a single directory: two same-named videos sitting in different
        sub-directories of one category would otherwise share a single key and thus a
        single thumbnail. The id is also stable across renames and migrations, so the
        stored thumbnail survives a video moving to another directory or category.

        :param video_id: The database id of the video to compute the thumbnail path for.
        :type video_id: str
        :return: The computed storage path for the thumbnail.
        :rtype: str
        """
        cfg = self.settings.thumbnail_config
        return self._storage_handler.join_path(
            "thumbnails", cfg.storage_pseudo_name, f"{video_id}.jpg"
        )

    @staticmethod
    def _build_thumbnail_response(
        thumbnail_bytes: bytes, background: BackgroundTask | None = None,
    ) -> StreamingResponse:
        """
        Build a StreamingResponse for the thumbnail image bytes with appropriate headers.

        :param thumbnail_bytes: The thumbnail image bytes.
        :type thumbnail_bytes: bytes
        :return: A StreamingResponse containing the thumbnail image.
        :rtype: StreamingResponse
        """
        return StreamingResponse(
            content=io.BytesIO(thumbnail_bytes),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
            background=background,
        )
