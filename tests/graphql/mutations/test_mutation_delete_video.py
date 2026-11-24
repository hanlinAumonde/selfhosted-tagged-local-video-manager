"""Tests for the ``deleteVideo`` mutation."""

from bson import ObjectId
import pytest

from src.platform.jobs.task_model import TaskStatus

from src.features.catalog.video import VideoModel
from src.features.catalog.video_tag import VideoTagModel
from tests.graphql.helpers import (
    DELETE_VIDEO,
    assert_error_contains,
    assert_no_errors,
)


pytestmark = pytest.mark.mutation


async def test_delete_video_removes_from_db(
    execute_gql, video_factory, mock_handler, mock_dir_metadata_service
):
    video = await video_factory(name="to-delete")

    result = await execute_gql(DELETE_VIDEO, {"videoId": str(video.id)})

    assert_no_errors(result)
    assert result.data["deleteVideo"]["success"] is True
    assert result.data["deleteVideo"]["video"] is None

    assert await VideoModel.get(video.id) is None
    mock_handler.delete_file.assert_called_once()
    mock_dir_metadata_service.update_directory_metadata_forward.assert_awaited_once()


async def test_delete_video_decrements_tag_counts(
    execute_gql, video_factory, tag_factory
):
    await tag_factory(name="alpha", tag_count=2)
    await tag_factory(name="beta", tag_count=1)
    video = await video_factory(name="v", tags=["alpha", "beta"])

    result = await execute_gql(DELETE_VIDEO, {"videoId": str(video.id)})
    assert_no_errors(result)

    alpha = await VideoTagModel.find_one({"name": "alpha"})
    beta = await VideoTagModel.find_one({"name": "beta"})

    assert alpha.tag_count == 1
    # beta hits zero and is deleted by tag_operation_service.
    assert beta is None


async def test_delete_video_not_found(execute_gql, init_db):
    missing = str(ObjectId())
    result = await execute_gql(DELETE_VIDEO, {"videoId": missing})
    assert_error_contains(result, missing)


async def test_delete_video_invalid_id(execute_gql, init_db):
    result = await execute_gql(DELETE_VIDEO, {"videoId": "garbage"})
    assert_error_contains(result, "delete_video")


async def test_delete_video_missing_argument(execute_gql, init_db):
    result = await execute_gql(DELETE_VIDEO, {})
    assert_error_contains(result, "videoId")


# ----------------------------- Migration lock --------------------------------

async def test_delete_video_migration_locked(execute_gql, video_factory, task_factory):
    video = await video_factory(name="locked-video")
    await task_factory(source_path=video.path, status=TaskStatus.PROCESSING)

    result = await execute_gql(DELETE_VIDEO, {"videoId": str(video.id)})

    assert_error_contains(result, "being migrated")
