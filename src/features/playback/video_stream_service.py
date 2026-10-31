from typing import AsyncGenerator

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from src.features.catalog.video import VideoModel
from src.logger import get_logger
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.base_resource_handler import BaseResourceHandler
from src.platform.storage.resource_handler_service import ResourceHandlerService

logger = get_logger("video_stream_resolver")

# Browser-natively-supported formats that don't need transcoding
BROWSER_SUPPORTED_EXTENSIONS = {"mp4", "webm"}

class VideoStreamService:

    def __init__(self, resourceHandlerService: ResourceHandlerService, ffmpegService: FFmpegService):
        self.resourceHandlerService = resourceHandlerService
        self.ffmpegService = ffmpegService

    async def video_stream_resolver(self, 
                                    video_id: str, 
                                    request: Request) -> StreamingResponse:
        """
        Handles video streaming requests and supports Range requests (for drag-and-drop playback in Video.js).
        For non-browser-supported formats, transcodes to MP4 on-the-fly using ffmpeg.

        :param video_id: The ID of the video to stream.
        :type video_id: str
        :param request: The incoming HTTP request, used to access headers for Range requests.
        :type request: Request
        :return: A StreamingResponse that streams the video content to the client.
        :rtype: StreamingResponse
        """
        video = await VideoModel.get(video_id)
        if not video:
            raise HTTPException(status_code=404, detail="video metadata doesn't exist")

        handler = self.resourceHandlerService.get_handler(video.category)
        video_fs_path = AbsolutePath.from_existing_path(
            path=video.path, 
            category=video.category,
            handler=handler
        ).FS_format_path()
        # One round-trip answers both "is it there" and "how big is it": on S3 each of
        # those used to be its own request, on every Range request a player sends.
        file_info = await handler.stat(video_fs_path)
        if file_info is None:
            raise HTTPException(status_code=404, detail="video file doesn't exist")

        ext = handler.get_file_extension(video_fs_path).lower()

        # Non-browser-supported formats: transcode to MP4 on-the-fly
        if ext not in BROWSER_SUPPORTED_EXTENSIONS:
            return await self._stream_transcoded(handler, video_fs_path)

        # Browser-supported formats: direct streaming with Range support
        file_size = file_info.size
        range_header = request.headers.get("Range")

        try:
            if range_header:
                # bytes=start-end
                byte_range = range_header.replace("bytes=", "").split("-")
                start = int(byte_range[0]) if byte_range[0] else 0
                end = int(byte_range[1]) if byte_range[1] else file_size - 1

                # Ensure the scope is valid
                if start >= file_size or end >= file_size:
                    raise HTTPException(
                        status_code=416,
                        detail="The requested scope is invalid.",
                        headers={"Content-Range": f"bytes */{file_size}"}
                    )

                content_length = end - start + 1

                return StreamingResponse(
                    self._iter_file_chunks(handler, video_fs_path, 1024*1024, start, content_length),
                    status_code=206,
                    headers={
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(content_length),
                        "Content-Type": self.get_video_mime_type(video_fs_path, handler),
                    },
                    media_type=self.get_video_mime_type(video_fs_path, handler)
                )

            else:
                return StreamingResponse(
                    self._iter_file_chunks(handler, video_fs_path, 1024*1024, 0, int(file_size)),
                    headers={
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(file_size),
                        "Content-Type": self.get_video_mime_type(video_fs_path, handler),
                    },
                    media_type=self.get_video_mime_type(video_fs_path, handler)
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error while processing video stream request: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    async def _stream_transcoded(self, 
                                 handler: BaseResourceHandler, 
                                 video_fs_path: str) -> StreamingResponse:
        """
        Transcode video to fragmented MP4 on-the-fly using ffmpeg and stream the output.
        Range requests are not supported for transcoded streams.

        :param handler: The resource handler to read the video file
        :type handler: BaseResourceHandler
        :param video_fs_path: The file system path to the video file
        :type video_fs_path: str
        :return: A StreamingResponse for the transcoded video
        :rtype: StreamingResponse
        """
        return StreamingResponse(
            self.ffmpegService.transcode_to_mp4_stream(handler, video_fs_path),
            media_type="video/mp4",
            headers={"Content-Type": "video/mp4"},
        )

    async def _iter_file_chunks(self, 
                                handler: BaseResourceHandler, 
                                path: str,
                                chunk_size: int, 
                                start: int, 
                                content_length: int) -> AsyncGenerator[bytes, None]:
        """
        Asynchronously read a file in chunks and yield the bytes for streaming.

        :param handler: The resource handler to read the file
        :type handler: BaseResourceHandler
        :param path: The file system path to the video file
        :type path: str
        :param chunk_size: The size of each chunk to read in bytes
        :type chunk_size: int
        :param start: The starting byte offset to read from
        :type start: int
        :param content_length: The total number of bytes to read
        :type content_length: int
        :return: An asynchronous generator yielding chunks of file data
        :rtype: AsyncGenerator[bytes, None]
        """
        remaining = content_length
        offset = start
        while remaining > 0:
            read_size = min(chunk_size, remaining)
            chunk = await handler.read_file_chunk(path, offset, read_size)
            if not chunk:
                break
            offset += len(chunk)
            remaining -= len(chunk)
            yield chunk

    def get_video_mime_type(self, file_path: str, handler: BaseResourceHandler) -> str:
        """
        Returns the correct MIME type based on the file extension.

        :param file_path: The file system path to the video file
        :type file_path: str
        :param handler: The resource handler to get the file extension
        :type handler: BaseResourceHandler
        :return: The MIME type for the video file
        :rtype: str
        """
        ext = handler.get_file_extension(file_path).lower()
        mime_types = {
            "mp4": "video/mp4",
            "webm": "video/webm"
        }
        return mime_types.get(ext, "video/mp4")
