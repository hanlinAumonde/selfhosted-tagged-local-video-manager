"""Which error VideoStreamService raises when a stream cannot be served, and the 206 it
returns when it can."""

import pytest
from bson import ObjectId
from fastapi import Request, status

from src.errors import InvalidRangeError, VideoFileNotFoundError, VideoNotFoundError
from src.features.playback.video_stream_service import VideoStreamService

pytestmark = pytest.mark.unit


def _request(range_header: str | None = None) -> Request:
    headers = [(b"range", range_header.encode())] if range_header else []
    return Request({"type": "http", "headers": headers})


@pytest.fixture
def stream_svc(handler_svc, ffmpeg_svc, handler) -> VideoStreamService:
    # The shared mock handler reports a 1024-byte file.
    handler.get_file_extension.return_value = "mp4"
    return VideoStreamService(handler_svc, ffmpeg_svc)


async def test_unknown_video_id_raises_video_not_found(stream_svc, init_db):
    """
    Given no video record with the requested id
    When the stream is requested
    Then VideoNotFoundError is raised carrying that id
    """
    video_id = str(ObjectId())

    with pytest.raises(VideoNotFoundError) as exc_info:
        await stream_svc.video_stream_resolver(video_id, _request())

    assert exc_info.value.video_id == video_id


async def test_missing_file_raises_video_file_not_found(
    stream_svc, init_db, video_factory, handler,
):
    """
    Given a video record whose file is no longer in storage
    When the stream is requested
    Then VideoFileNotFoundError is raised
    """
    video = await video_factory(name="gone")
    handler.stat.return_value = None

    with pytest.raises(VideoFileNotFoundError):
        await stream_svc.video_stream_resolver(str(video.id), _request())


async def test_range_past_the_end_raises_invalid_range(stream_svc, init_db, video_factory):
    """
    Given a 1024-byte mp4 video
    When the stream is requested with "Range: bytes=2000-"
    Then InvalidRangeError is raised carrying the file size 1024
    """
    video = await video_factory(name="v")

    with pytest.raises(InvalidRangeError) as exc_info:
        await stream_svc.video_stream_resolver(str(video.id), _request("bytes=2000-"))

    assert exc_info.value.file_size == 1024


async def test_satisfiable_range_returns_partial_content(stream_svc, init_db, video_factory):
    """
    Given a 1024-byte mp4 video
    When the stream is requested with "Range: bytes=0-99"
    Then the response status is 206
    And its Content-Range header is "bytes 0-99/1024"
    And its Content-Length header is "100"
    """
    video = await video_factory(name="v")

    response = await stream_svc.video_stream_resolver(str(video.id), _request("bytes=0-99"))

    assert response.status_code == status.HTTP_206_PARTIAL_CONTENT
    assert response.headers["Content-Range"] == "bytes 0-99/1024"
    assert response.headers["Content-Length"] == "100"
