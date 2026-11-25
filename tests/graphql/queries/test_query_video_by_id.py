"""Tests for the ``getVideoById`` query."""

from bson import ObjectId
import pytest

from tests.graphql.helpers import (
    GET_VIDEO_BY_ID,
    assert_error_contains,
    assert_no_errors,
)


pytestmark = pytest.mark.query


async def test_get_video_by_id_returns_video(execute_gql, video_factory):
    video = await video_factory(name="hello-video", author="alice", loved=True)
    result = await execute_gql(GET_VIDEO_BY_ID, {"videoId": str(video.id)})

    assert_no_errors(result)
    payload = result.data["getVideoById"]
    assert payload["id"] == str(video.id)
    assert payload["name"] == "hello-video"
    assert payload["author"] == "alice"
    assert payload["loved"] is True
    assert payload["duration"] == 120.0
    assert payload["tags"] == []


async def test_get_video_by_id_with_tags(execute_gql, video_factory):
    video = await video_factory(name="tagged", tags=["action", "drama"])
    result = await execute_gql(GET_VIDEO_BY_ID, {"videoId": str(video.id)})

    assert_no_errors(result)
    tag_names = sorted(t["name"] for t in result.data["getVideoById"]["tags"])
    assert tag_names == ["action", "drama"]


async def test_get_video_by_id_unlocked_by_default(execute_gql, video_factory):
    video = await video_factory(name="free")
    result = await execute_gql(GET_VIDEO_BY_ID, {"videoId": str(video.id)})

    assert_no_errors(result)
    assert result.data["getVideoById"]["isLocked"] is False


async def test_get_video_by_id_reports_migration_lock(execute_gql, video_factory):
    """A video mid-migration is still returned, but flagged so the UI can block playback."""
    import time

    from src.features.migration.migration_task_model import MigrationTaskModel
    from src.platform.jobs.task_model import TaskStatus

    video = await video_factory(name="moving")
    now = time.time()
    await MigrationTaskModel(
        source_path=video.path,
        source_category=video.category,
        target_path="Target-category/Target-resource/moving.mp4",
        target_category="Target-category",
        file_name="moving",
        file_size=100,
        status=TaskStatus.PROCESSING,
        created_at=now,
        updated_at=now,
    ).insert()

    result = await execute_gql(GET_VIDEO_BY_ID, {"videoId": str(video.id)})

    assert_no_errors(result)
    assert result.data["getVideoById"]["isLocked"] is True
    assert result.data["getVideoById"]["name"] == "moving"


async def test_get_video_by_id_not_found(execute_gql, init_db):
    missing_id = str(ObjectId())
    result = await execute_gql(GET_VIDEO_BY_ID, {"videoId": missing_id})

    assert_error_contains(result, missing_id)


async def test_get_video_by_id_invalid_object_id(execute_gql, init_db):
    result = await execute_gql(GET_VIDEO_BY_ID, {"videoId": "not-a-valid-oid"})

    # Resolver wraps the bson failure as a DatabaseOperationError.
    assert_error_contains(result, "get video by id")


async def test_get_video_by_id_missing_required_argument(execute_gql, init_db):
    result = await execute_gql(GET_VIDEO_BY_ID, {})

    # Strawberry rejects the request before invoking the resolver.
    assert_error_contains(result, "videoId")