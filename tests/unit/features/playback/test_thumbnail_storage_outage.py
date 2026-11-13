"""ThumbnailService — an unreachable thumbnail storage is skipped instead of awaited."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Settings
from src.features.catalog.video import VideoModel
from src.features.playback.thumbnail_service import ThumbnailService
from src.platform.storage.local_fs.local_fs_handler import LocalFSResourceHandler
from .conftest import STORAGE_COOLDOWN, body_of, run_attached_work

pytestmark = pytest.mark.unit


def _stored_key(video: VideoModel) -> str:
    return f"thumbnails/Test-resource/{video.id}.jpg"


async def _video_with_stored_thumbnail(video_factory, name: str) -> VideoModel:
    video = await video_factory(name=name)
    await video.set({"thumbnail": _stored_key(video)})
    return video


async def _fetch(svc, video: VideoModel) -> bytes:
    """Request a thumbnail the way the server serves it: body first, attached work after."""
    response = await svc.get_thumbnail(str(video.id))
    body = await body_of(response)
    await run_attached_work(response)
    return body


@pytest.fixture
def unreachable_storage(thumb_svc_with_storage):
    storage = thumb_svc_with_storage._storage_handler
    storage.read_file.side_effect = ConnectionError("storage unreachable")
    storage.write_file = AsyncMock(side_effect=ConnectionError("storage unreachable"))
    return storage


async def _open_the_breaker(svc, video_factory) -> None:
    """Hit the unreachable storage once, through an ordinary request."""
    await _fetch(svc, await _video_with_stored_thumbnail(video_factory, "trigger"))


async def test_failed_read_makes_following_requests_skip_storage(
    thumb_svc_with_storage, video_factory,
):
    # Given thumbnail storage is configured but every read raises
    storage = thumb_svc_with_storage._storage_handler
    storage.read_file.side_effect = ConnectionError("storage unreachable")
    # And three videos whose thumbnails were all stored earlier
    first, second, third = [
        await _video_with_stored_thumbnail(video_factory, name) for name in ("a", "b", "c")
    ]
    # And the first video's thumbnail has been requested, hitting the failure
    await _fetch(thumb_svc_with_storage, first)

    # When the other two videos' thumbnails are requested within the cooldown
    bodies = [await _fetch(thumb_svc_with_storage, video) for video in (second, third)]

    # Then each response carries the generated JPEG
    assert bodies == [b"JPEG-DATA", b"JPEG-DATA"]
    # And storage was read only once, for the first video
    assert storage.read_file.await_count == 1
    # And nothing is written to storage for any of the three
    storage.write_file.assert_not_called()


async def test_failed_write_makes_following_requests_skip_storage(
    thumb_svc_with_storage, video_factory,
):
    # Given thumbnail storage is configured but every write raises
    storage = thumb_svc_with_storage._storage_handler
    storage.write_file = AsyncMock(side_effect=ConnectionError("storage unreachable"))
    # And three videos with no stored thumbnail
    first, second, third = [await video_factory(name=name) for name in ("a", "b", "c")]
    # And the first video's thumbnail has been requested and its write has failed
    await _fetch(thumb_svc_with_storage, first)

    # When the other two videos' thumbnails are requested within the cooldown
    bodies = [await _fetch(thumb_svc_with_storage, video) for video in (second, third)]

    # Then each response carries the generated JPEG
    assert bodies == [b"JPEG-DATA", b"JPEG-DATA"]
    # And storage was written to only once, for the first video
    assert storage.write_file.await_count == 1


async def test_skipped_storage_leaves_the_recorded_thumbnail_key_alone(
    thumb_svc_with_storage, unreachable_storage, video_factory,
):
    # Given storage is being skipped after a failure
    await _open_the_breaker(thumb_svc_with_storage, video_factory)
    unreachable_storage.read_file.side_effect = None
    unreachable_storage.write_file = AsyncMock()
    # And two videos, one with a stored thumbnail key and one without
    kept = await _video_with_stored_thumbnail(video_factory, "kept")
    bare = await video_factory(name="bare")

    # When both thumbnails are requested within the cooldown
    await _fetch(thumb_svc_with_storage, kept)
    await _fetch(thumb_svc_with_storage, bare)

    # Then the first video still points at its stored key
    assert (await VideoModel.get(kept.id)).thumbnail == _stored_key(kept)
    # And the second video still has no thumbnail key
    assert (await VideoModel.get(bare.id)).thumbnail is None


async def test_storage_is_tried_again_after_the_cooldown(
    thumb_svc_with_storage, unreachable_storage, video_factory, ffmpeg_svc, clock,
):
    # Given storage is being skipped after a failure
    await _open_the_breaker(thumb_svc_with_storage, video_factory)
    # And storage has recovered
    unreachable_storage.read_file.side_effect = None
    unreachable_storage.read_file.return_value = b"STORED-JPEG"
    # And two videos whose thumbnails were stored earlier
    first, second = [
        await _video_with_stored_thumbnail(video_factory, name) for name in ("a", "b")
    ]
    ffmpeg_svc.generate_thumbnail.reset_mock()

    # When the cooldown has elapsed and both thumbnails are requested
    clock.advance(STORAGE_COOLDOWN + 1)
    bodies = [await _fetch(thumb_svc_with_storage, video) for video in (first, second)]

    # Then both responses carry the stored JPEG
    assert bodies == [b"STORED-JPEG", b"STORED-JPEG"]
    # And nothing is generated for them
    ffmpeg_svc.generate_thumbnail.assert_not_called()


async def test_only_one_request_probes_storage_after_the_cooldown(
    thumb_svc_with_storage, unreachable_storage, video_factory, clock,
):
    # Given storage is being skipped after a failure, and is still down
    await _open_the_breaker(thumb_svc_with_storage, video_factory)
    # And the cooldown has elapsed
    clock.advance(STORAGE_COOLDOWN + 1)
    # And three videos whose thumbnails were stored earlier
    first, second, third = [
        await _video_with_stored_thumbnail(video_factory, name) for name in ("a", "b", "c")
    ]
    # And a request for the first video is still waiting on its storage read
    reading = asyncio.Event()
    gate = asyncio.Event()

    async def _read_that_hangs_then_fails(path: str) -> bytes:
        reading.set()
        await gate.wait()
        raise ConnectionError("storage unreachable")

    unreachable_storage.read_file.side_effect = _read_that_hangs_then_fails
    probe = asyncio.create_task(_fetch(thumb_svc_with_storage, first))
    await asyncio.wait_for(reading.wait(), timeout=2)
    reads_so_far = unreachable_storage.read_file.await_count

    # When the other two videos' thumbnails are requested
    # Then both are answered with the generated JPEG without waiting for the first
    bodies = [
        await asyncio.wait_for(_fetch(thumb_svc_with_storage, video), timeout=2)
        for video in (second, third)
    ]
    assert bodies == [b"JPEG-DATA", b"JPEG-DATA"]
    # And storage was not read for either of them
    assert unreachable_storage.read_file.await_count == reads_so_far

    gate.set()
    await probe


async def test_failed_probe_starts_another_cooldown(
    thumb_svc_with_storage, unreachable_storage, video_factory, clock,
):
    # Given storage is being skipped after a failure, and is still down
    await _open_the_breaker(thumb_svc_with_storage, video_factory)
    # And three videos whose thumbnails were stored earlier
    first, second, third = [
        await _video_with_stored_thumbnail(video_factory, name) for name in ("a", "b", "c")
    ]
    # And the cooldown has elapsed and the first video's request has probed storage and failed
    clock.advance(STORAGE_COOLDOWN + 1)
    await _fetch(thumb_svc_with_storage, first)
    reads_so_far = unreachable_storage.read_file.await_count

    # When the other two videos' thumbnails are requested right after
    for video in (second, third):
        await _fetch(thumb_svc_with_storage, video)

    # Then storage is not read for either of them
    assert unreachable_storage.read_file.await_count == reads_so_far


async def test_service_built_without_a_breaker_still_skips_a_failed_storage(
    handler_svc, ffmpeg_svc, video_factory,
):
    # Given a thumbnail service built without being handed a breaker
    svc = ThumbnailService(
        resource_handler_service=handler_svc,
        ffmpeg_service=ffmpeg_svc,
        settings=Settings.model_validate({
            "resource_paths": {"Test-category": {"Test-resource": "/test"}},
            "thumbnail_config": {
                "storage_category": "Test-category",
                "storage_pseudo_name": "Test-resource",
            },
        }),
    )
    # And its storage is configured but every read raises
    storage = MagicMock(spec=LocalFSResourceHandler, name="storage_handler")
    storage.join_path.side_effect = lambda *parts: "/".join(parts)
    storage.read_file.side_effect = ConnectionError("storage unreachable")
    svc._storage_handler = storage
    # And three videos whose thumbnails were all stored earlier
    first, second, third = [
        await _video_with_stored_thumbnail(video_factory, name) for name in ("a", "b", "c")
    ]
    # And the first video's thumbnail has been requested, hitting the failure
    await _fetch(svc, first)

    # When the other two videos' thumbnails are requested right after
    for video in (second, third):
        await _fetch(svc, video)

    # Then storage was read only once, for the first video
    assert storage.read_file.await_count == 1


async def test_missing_thumbnail_is_not_treated_as_an_outage(
    thumb_svc_with_storage, video_factory,
):
    # Given thumbnail storage is configured and reachable
    storage = thumb_svc_with_storage._storage_handler
    # And three videos whose recorded thumbnails no longer exist in storage
    storage.read_file.return_value = None
    videos = [await _video_with_stored_thumbnail(video_factory, name) for name in ("a", "b", "c")]

    # When all three thumbnails are requested one after another
    for video in videos:
        await _fetch(thumb_svc_with_storage, video)

    # Then storage is read for each of them
    assert storage.read_file.await_count == 3
    # And each regenerated thumbnail is written back to storage
    assert storage.write_file.await_count == 3
