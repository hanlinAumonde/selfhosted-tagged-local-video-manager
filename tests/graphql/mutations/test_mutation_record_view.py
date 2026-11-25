"""Tests for the ``recordVideoView`` mutation."""

from bson import ObjectId
import pytest

from src.features.catalog.video_model import VideoModel
from tests.graphql.helpers import (
    RECORD_VIDEO_VIEW,
    assert_error_contains,
    assert_no_errors,
)


pytestmark = pytest.mark.mutation


async def test_record_video_view_increments_count(execute_gql, video_factory):
    video = await video_factory(name="v", viewCount=2, lastViewTime=0.0)

    result = await execute_gql(RECORD_VIDEO_VIEW, {"videoId": str(video.id)})

    assert_no_errors(result)
    payload = result.data["recordVideoView"]
    assert payload["success"] is True
    assert payload["video"]["viewCount"] == 3
    assert payload["video"]["lastViewTime"] > 0.0

    # DB also reflects the change.
    refreshed = await VideoModel.get(video.id)
    assert refreshed.viewCount == 3
    assert refreshed.lastViewTime == payload["video"]["lastViewTime"]


async def test_record_video_view_starts_from_zero(execute_gql, video_factory):
    video = await video_factory(name="v", viewCount=None, lastViewTime=None)

    result = await execute_gql(RECORD_VIDEO_VIEW, {"videoId": str(video.id)})

    assert_no_errors(result)
    assert result.data["recordVideoView"]["video"]["viewCount"] == 1


async def test_record_video_view_not_found(execute_gql, init_db):
    missing = str(ObjectId())
    result = await execute_gql(RECORD_VIDEO_VIEW, {"videoId": missing})
    assert_error_contains(result, missing)


async def test_record_video_view_invalid_id(execute_gql, init_db):
    result = await execute_gql(RECORD_VIDEO_VIEW, {"videoId": "not-an-oid"})
    assert_error_contains(result, "record_video_view")


async def test_record_video_view_missing_argument(execute_gql, init_db):
    result = await execute_gql(RECORD_VIDEO_VIEW, {})
    assert_error_contains(result, "videoId")
