"""ThumbnailService — a generated thumbnail is answered first and persisted afterwards."""

from unittest.mock import AsyncMock

import pytest
from beanie.operators import Set

from src.features.catalog.video import VideoModel
from .conftest import body_of

pytestmark = pytest.mark.unit


def _stored_key(video: VideoModel) -> str:
    return f"thumbnails/Test-resource/{video.id}.jpg"


async def test_generated_thumbnail_is_returned_before_it_is_stored(
    thumb_svc_with_storage, video_factory,
):
    # Given thumbnail storage is configured
    storage = thumb_svc_with_storage._storage_handler
    # And a video that has no stored thumbnail yet
    video = await video_factory(name="v")

    # When its thumbnail is requested
    response = await thumb_svc_with_storage.get_thumbnail(str(video.id))

    # Then the response carries the generated JPEG
    assert await body_of(response) == b"JPEG-DATA"
    # And nothing has been written to storage yet
    storage.write_file.assert_not_called()
    # And the video document does not point at a stored thumbnail yet
    assert (await VideoModel.get(video.id)).thumbnail is None


async def test_stored_thumbnail_is_persisted_once_the_response_work_runs(
    thumb_svc_with_storage, video_factory,
):
    # Given thumbnail storage is configured
    storage = thumb_svc_with_storage._storage_handler
    # And a thumbnail response for a video that had no stored thumbnail
    video = await video_factory(name="v")
    response = await thumb_svc_with_storage.get_thumbnail(str(video.id))

    # When the work attached to the response runs
    assert response.background is not None
    await response.background()

    # Then the generated JPEG is written under "thumbnails/Test-resource/{video id}.jpg"
    storage.write_file.assert_awaited_once_with(_stored_key(video), b"JPEG-DATA")
    # And the video document points at that key
    assert (await VideoModel.get(video.id)).thumbnail == _stored_key(video)


async def test_missing_duration_is_filled_in_after_the_response(thumb_svc, video_factory):
    # Given a video whose duration is 0
    video = await video_factory(name="v", duration=0.0)

    # When its thumbnail is requested
    response = await thumb_svc.get_thumbnail(str(video.id))

    # Then the duration has not been probed when the response is returned
    assert (await VideoModel.get(video.id)).duration == 0.0

    # When the work attached to the response runs
    assert response.background is not None
    await response.background()

    # Then the video document carries the probed duration
    assert (await VideoModel.get(video.id)).duration == 120.0


async def test_persisting_does_not_overwrite_an_edit_made_meanwhile(
    thumb_svc_with_storage, video_factory,
):
    # Given thumbnail storage is configured
    # And a thumbnail response for a video named "before"
    video = await video_factory(name="before")
    response = await thumb_svc_with_storage.get_thumbnail(str(video.id))
    # And the video is renamed to "after" before the work attached to the response runs
    await VideoModel.find_one(VideoModel.id == video.id).update(Set({VideoModel.name: "after"}))

    # When that work runs
    assert response.background is not None
    await response.background()

    # Then the video document is still named "after"
    refreshed = await VideoModel.get(video.id)
    assert refreshed.name == "after"
    # And it points at the stored thumbnail
    assert refreshed.thumbnail == _stored_key(video)


async def test_failed_store_does_not_record_a_thumbnail_key(
    thumb_svc_with_storage, video_factory,
):
    # Given thumbnail storage is configured and rejects writes
    storage = thumb_svc_with_storage._storage_handler
    storage.write_file = AsyncMock(side_effect=RuntimeError("write refused"))
    # And a thumbnail response for a video that had no stored thumbnail
    video = await video_factory(name="v")
    response = await thumb_svc_with_storage.get_thumbnail(str(video.id))

    # When the work attached to the response runs
    # Then no error escapes
    if response.background is not None:
        await response.background()

    # And the video document still has no thumbnail key
    assert (await VideoModel.get(video.id)).thumbnail is None


async def test_stored_thumbnail_hit_schedules_no_work(thumb_svc_with_storage, video_factory):
    # Given a video whose thumbnail is already in storage
    video = await video_factory(name="v")
    await video.set({"thumbnail": _stored_key(video)})

    # When its thumbnail is requested
    response = await thumb_svc_with_storage.get_thumbnail(str(video.id))

    # Then the stored JPEG is returned
    assert await body_of(response) == b"STORED-JPEG"
    # And the response has no work attached to it
    assert response.background is None
