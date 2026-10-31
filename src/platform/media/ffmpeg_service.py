import asyncio
from asyncio.subprocess import Process
import os
from typing import AsyncIterator
from src.logger import get_logger
from src.platform.storage.base_resource_handler import BaseResourceHandler

logger = get_logger("ffmpeg_service")

class FFmpegService:

    def __init__(self, semaphore_limit: int):
        self._semaphore = asyncio.Semaphore(
            max(
                semaphore_limit,
                os.cpu_count() // 2
            )
        )

    # --- Thumbnail generation ---

    async def generate_thumbnail(self, handler: BaseResourceHandler, fs_path: str) -> bytes:
        """
        Generate a JPEG thumbnail from video.
        Tries capturing at 10s first, falls back to 0s if video is too short.

        :param handler: The resource handler to access the video file.
        :type handler: BaseResourceHandler
        :param fs_path: The file system path to the video file.
        :type fs_path: str
        :return: The generated thumbnail image data in bytes.
        :rtype: bytes
        """
        async with self._semaphore:
            ffmpeg_input = handler.get_ffmpeg_accessible_path(fs_path)
            if ffmpeg_input:
                try:
                    return await self._run_thumbnail_command(ffmpeg_input, ss=10)
                except Exception as e:
                    logger.warning(f"Thumbnail at 10s failed for {fs_path}: {e}, retrying at 0s")
                    return await self._run_thumbnail_command(ffmpeg_input, ss=0)
            else:
                return await self._run_thumbnail_piped(handler, fs_path)

    @staticmethod
    async def _run_thumbnail_command(ffmpeg_input: str, ss: float) -> bytes:
        """
        Direct mode: -ss before -i for fast seeking.

        :param ffmpeg_input: The input path for ffmpeg.
        :type ffmpeg_input: str
        :param ss: The timestamp in seconds to capture the thumbnail.
        :type ss: float
        :return: The generated thumbnail image data in bytes.
        :rtype: bytes
        """
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-loglevel", "error",
            "-ss", str(ss),
            "-i", ffmpeg_input,
            "-frames:v", "1",
            "-f", "image2",
            "-vcodec", "mjpeg",
            "-vf", "scale=320:-1",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {stderr.decode(errors='replace')}")
        if not stdout:
            raise RuntimeError("ffmpeg produced no thumbnail data")
        return stdout

    async def _run_thumbnail_piped(self, handler: BaseResourceHandler, fs_path: str) -> bytes:
        """
        Pipe fallback: feed file via stdin. -ss must go after -i (no seeking on pipe).

        :param handler: The resource handler to access the video file.
        :type handler: BaseResourceHandler
        :param fs_path: The file system path to the video file.
        :type fs_path: str
        :return: The generated thumbnail image data in bytes.
        :rtype: bytes
        """
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-loglevel", "error",
            "-i", "pipe:0",
            "-ss", "10",
            "-frames:v", "1",
            "-f", "image2",
            "-vcodec", "mjpeg",
            "-vf", "scale=320:-1",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await self._feed_stdin(handler, fs_path, process.stdin)
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg piped failed: {stderr.decode(errors='replace')}")
        if not stdout:
            raise RuntimeError("ffmpeg produced no thumbnail data")
        return stdout

    # --- Duration extraction ---

    async def get_video_duration(self, handler: BaseResourceHandler, fs_path: str) -> float:
        """Get video duration in seconds using ffprobe."""
        async with self._semaphore:
            try:
                ffmpeg_input = handler.get_ffmpeg_accessible_path(fs_path)
                if ffmpeg_input:
                    return await self._run_duration_command(ffmpeg_input)
                else:
                    return await self._run_duration_piped(handler, fs_path)
            except Exception as e:
                logger.warning(f"Failed to get duration for {fs_path}: {e}")
                return 0.0

    @staticmethod
    async def _run_duration_command(ffmpeg_input: str) -> float:
        """
        Run ffprobe command to get video duration.

        :param ffmpeg_input: The input path for ffprobe.
        :type ffmpeg_input: str
        :return: The duration of the video in seconds.
        :rtype: float
        """
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            ffmpeg_input,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {stderr.decode(errors='replace')}")
        return float(stdout)

    async def _run_duration_piped(self, handler: BaseResourceHandler, fs_path: str) -> float:
        """
        Run ffprobe in piped mode to get video duration.

        :param handler: The resource handler to access the video file.
        :type handler: BaseResourceHandler
        :param fs_path: The file system path to the video file.
        :type fs_path: str
        :return: The duration of the video in seconds.
        :rtype: float
        """
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            "pipe:0",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await self._feed_stdin(handler, fs_path, process.stdin)
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"ffprobe piped failed: {stderr.decode(errors='replace')}")
        return float(stdout)

    # --- Live transcoding to MP4 ---

    async def transcode_to_mp4_stream(
        self, handler: BaseResourceHandler, fs_path: str
    ) -> AsyncIterator[bytes]:
        """
        Transcode video to fragmented MP4 on-the-fly.
        Returns an async iterator that yields 1MB chunks.
        The semaphore is held for the entire duration of the stream.

        :param handler: The resource handler to access the video file.
        :type handler: BaseResourceHandler
        :param fs_path: The file system path to the video file.
        :type fs_path: str
        :return: An asynchronous iterator yielding chunks of the transcoded video data.
        :rtype: AsyncIterator[bytes]
        """
        await self._semaphore.acquire()

        ffmpeg_input = handler.get_ffmpeg_accessible_path(fs_path)
        if not ffmpeg_input:
            self._semaphore.release()
            raise RuntimeError(f"Cannot get accessible path for transcoding: {fs_path}")

        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-loglevel", "error",
                "-i", ffmpeg_input,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4",
                "pipe:1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            self._semaphore.release()
            logger.exception(f"Failed to start ffmpeg transcoding: {e}")
            raise

        async for chunk in self._iter_process_output(process):
            yield chunk

    # --- Internal helpers ---

    async def _iter_process_output(self, process: Process):
        """
        Read stdout in 1MB chunks, clean up process and release semaphore when done.

        :param process: The subprocess process to read from.
        :type process: Process
        :return: An asynchronous iterator yielding chunks of the process output.
        :rtype: AsyncIterator[bytes]
        """
        try:
            while True:
                chunk = await process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
            await process.wait()
            if process.returncode != 0:
                stderr_output = await process.stderr.read()
                logger.error(
                    f"ffmpeg transcoding failed (exit {process.returncode}): "
                    f"{stderr_output.decode(errors='replace')}"
                )
        except Exception as e:
            logger.error(f"Error during transcoding stream: {e}")
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            self._semaphore.release()

    @staticmethod
    async def _feed_stdin(
        handler: BaseResourceHandler, fs_path: str, stdin: asyncio.StreamWriter
    ):
        """
        Stream file content from handler into ffmpeg's stdin.

        :param handler: The resource handler to access the video file.
        :type handler: BaseResourceHandler
        :param fs_path: The file system path to the video file.
        :type fs_path: str
        :param stdin: The stdin stream of the ffmpeg process.
        :type stdin: asyncio.StreamWriter
        """
        try:
            file_info = await handler.stat(fs_path)
            if file_info is None:
                raise FileNotFoundError(fs_path)
            file_size = int(file_info.size)
            offset = 0
            chunk_size = 1024 * 1024
            while offset < file_size:
                length = min(chunk_size, file_size - offset)
                chunk = await handler.read_file_chunk(fs_path, offset, length)
                if not chunk:
                    break
                stdin.write(chunk)
                await stdin.drain()
                offset += len(chunk)
        except Exception as e:
            logger.error(f"Error feeding stdin for {fs_path}: {e}")
        finally:
            stdin.close()