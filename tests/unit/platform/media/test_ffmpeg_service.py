"""Unit tests for FFmpegService — thumbnail generation and video duration extraction."""

import pytest
from .conftest import _MockProcess
from src.platform.media.ffmpeg_service import FFmpegService

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# --------------------------- Thumbnail ----------------------------------
# -----------------------------------------------------------------------

async def test_generate_thumbnail_direct_succeeds_at_10s(
    queue_subprocess, handler_with_direct_path
):
    procs, calls = queue_subprocess
    procs.append(_MockProcess(stdout=b"JPEG"))

    svc = FFmpegService(semaphore_limit=1)
    result = await svc.generate_thumbnail(handler_with_direct_path, "/some/video.mp4")

    assert result == b"JPEG"
    # Only one ffmpeg invocation (the 10s capture).
    assert len(calls) == 1
    args, _ = calls[0]
    # -ss 10 should appear in args before -i.
    assert "-ss" in args and "10" in args
    assert "-i" in args
    assert args.index("-ss") < args.index("-i")


async def test_generate_thumbnail_falls_back_to_0s_on_failure(
    queue_subprocess, handler_with_direct_path
):
    procs, calls = queue_subprocess
    # First call returns failure, second returns the JPEG.
    procs.append(_MockProcess(returncode=1, stderr=b"video too short"))
    procs.append(_MockProcess(stdout=b"JPEG-AT-0"))

    svc = FFmpegService(semaphore_limit=1)
    result = await svc.generate_thumbnail(handler_with_direct_path, "/v.mp4")

    assert result == b"JPEG-AT-0"
    assert len(calls) == 2


async def test_generate_thumbnail_uses_piped_mode_when_no_direct_path(
    queue_subprocess, handler_with_piped_only
):
    procs, calls = queue_subprocess
    procs.append(_MockProcess(stdout=b"PIPED-JPEG"))

    svc = FFmpegService(semaphore_limit=1)
    result = await svc.generate_thumbnail(handler_with_piped_only, "/v.mp4")

    assert result == b"PIPED-JPEG"
    args, _ = calls[0]
    # Piped mode passes pipe:0 and -ss after -i (no fast-seek on pipe).
    assert "pipe:0" in args
    assert args.index("-i") < args.index("-ss")
    handler_with_piped_only.read_file_chunk.assert_called()


async def test_generate_thumbnail_raises_when_no_stdout(
    queue_subprocess, handler_with_direct_path
):
    procs, _ = queue_subprocess
    # Both retries return empty stdout — wrapper should raise.
    procs.append(_MockProcess(stdout=b""))
    procs.append(_MockProcess(stdout=b""))

    svc = FFmpegService(semaphore_limit=1)
    with pytest.raises(RuntimeError):
        await svc.generate_thumbnail(handler_with_direct_path, "/v.mp4")


# -----------------------------------------------------------------------
# --------------------------- Duration -----------------------------------
# -----------------------------------------------------------------------

async def test_get_video_duration_direct_returns_parsed_value(
    queue_subprocess, handler_with_direct_path
):
    procs, _ = queue_subprocess
    procs.append(_MockProcess(stdout=b"123.456\n"))

    svc = FFmpegService(semaphore_limit=1)
    duration = await svc.get_video_duration(handler_with_direct_path, "/v.mp4")
    assert duration == 123.456


async def test_get_video_duration_returns_zero_on_subprocess_failure(
    queue_subprocess, handler_with_direct_path
):
    procs, _ = queue_subprocess
    procs.append(_MockProcess(returncode=1, stderr=b"bad input"))

    svc = FFmpegService(semaphore_limit=1)
    duration = await svc.get_video_duration(handler_with_direct_path, "/v.mp4")
    assert duration == 0.0  # service swallows errors


async def test_get_video_duration_returns_zero_on_unparseable_output(
    queue_subprocess, handler_with_direct_path
):
    procs, _ = queue_subprocess
    procs.append(_MockProcess(stdout=b"not a number"))

    svc = FFmpegService(semaphore_limit=1)
    duration = await svc.get_video_duration(handler_with_direct_path, "/v.mp4")
    assert duration == 0.0


async def test_get_video_duration_uses_pipe_when_no_direct_path(
    queue_subprocess, handler_with_piped_only
):
    procs, calls = queue_subprocess
    procs.append(_MockProcess(stdout=b"60\n"))

    svc = FFmpegService(semaphore_limit=1)
    duration = await svc.get_video_duration(handler_with_piped_only, "/v.mp4")

    assert duration == 60.0
    args, _ = calls[0]
    assert "pipe:0" in args


# -----------------------------------------------------------------------
# --------------------------- Transcode ---------------------------------
# -----------------------------------------------------------------------

async def test_transcode_yields_chunks(
    queue_subprocess, handler_with_direct_path
):
    procs, calls = queue_subprocess
    procs.append(_MockProcess(stdout_chunks=[b"chunk1", b"chunk2"]))

    svc = FFmpegService(semaphore_limit=1)
    chunks = [c async for c in svc.transcode_to_mp4_stream(
        handler_with_direct_path, "/v.mp4"
    )]
    assert chunks == [b"chunk1", b"chunk2"]
    args, _ = calls[0]
    assert "libx264" in args


async def test_transcode_releases_semaphore_after_completion(
    queue_subprocess, handler_with_direct_path
):
    procs, _ = queue_subprocess
    procs.append(_MockProcess(stdout_chunks=[b"chunk1"]))

    svc = FFmpegService(semaphore_limit=1)
    async for _ in svc.transcode_to_mp4_stream(handler_with_direct_path, "/v.mp4"):
        pass

    # If semaphore wasn't released, subsequent acquire would block forever.
    procs.append(_MockProcess(stdout_chunks=[b"again"]))
    out = [c async for c in svc.transcode_to_mp4_stream(
        handler_with_direct_path, "/v.mp4"
    )]
    assert out == [b"again"]
