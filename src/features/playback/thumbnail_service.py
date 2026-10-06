import io
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from src.config import Settings
from src.features.catalog.video import VideoModel
from src.logger import get_logger
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.base_resource_handler import BaseResourceHandler
from src.platform.storage.resource_handler_service import ResourceHandlerService

logger = get_logger("thumbnail_service")

class ThumbnailService:
    def __init__(
        self,
        resource_handler_service: ResourceHandlerService,
        ffmpeg_service: FFmpegService,
        settings: Settings
    ):
        self.resourceHandlerService = resource_handler_service
        self.ffmpeg = ffmpeg_service
        self.settings = settings
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
        if not video_handler.file_exists(video_fs_path):
            logger.warning(f"Video file not found at path: {video_fs_path}")
            raise HTTPException(status_code=404, detail="Video file doesn't exist")

        # 2- try to read stored thumbnail (only if storage is configured)
        storage_path = (
            self._compute_thumbnail_storage_path(str(video.id))
            if self._storage_handler else None
        )
        if storage_path and video.thumbnail:
            if video.thumbnail == storage_path:
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

        # 4- persist to storage if configured, otherwise just update duration
        if storage_path:
            await self._store_thumbnail(storage_path, thumbnail_bytes)
            video.thumbnail = storage_path

        if video.duration == 0.0 or video.duration is None:
            video.duration = await self.ffmpeg.get_video_duration(video_handler, video_fs_path)
        await video.save()

        return self._build_thumbnail_response(thumbnail_bytes)

    async def _read_stored_thumbnail(self, thumbnail_path: str) -> bytes | None:
        """
        Try to read a previously stored thumbnail from the storage handler.

        :param thumbnail_path: The storage path of the thumbnail to read.
        :type thumbnail_path: str
        :return: The thumbnail bytes if found and readable, or None if not found or on error.
        :rtype: bytes | None
        """
        try:
            if not self._storage_handler.file_exists(thumbnail_path):
                return None
            size = self._storage_handler.get_size(thumbnail_path)
            return await self._storage_handler.read_file_chunk(thumbnail_path, 0, int(size))
        except Exception as e:
            logger.warning(f"Failed to read stored thumbnail at {thumbnail_path}: {e}")
            return None

    async def _store_thumbnail(self, path: str, data: bytes) -> None:
        """
        Store thumbnail bytes via the storage handler.

        :param path: The storage path where the thumbnail should be stored.
        :type path: str
        :param data: The thumbnail bytes to store.
        :type data: bytes
        """
        try:
            await self._storage_handler.write_file(path, data)
        except Exception as e:
            logger.exception(f"Failed to store thumbnail at {path}: {e}")

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
    def _build_thumbnail_response(thumbnail_bytes: bytes) -> StreamingResponse:
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
            headers={"Cache-Control": "public, max-age=3600"}
        )
