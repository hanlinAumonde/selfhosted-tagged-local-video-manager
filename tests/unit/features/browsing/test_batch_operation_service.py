"""Unit tests for BatchOperationService — batch update, delete, and sync operations."""

from pathlib import Path

import pytest

from src.features.catalog.video import VideoModel
from src.features.catalog.video_tag import VideoTagModel
from src.features.browsing.batch_operation_service import BatchResultType
from src.schema.types.pydantic_types.batch_operation_type import (
    SeriesOperationInputModel,
    SeriesOrderEntryInputModel,
    TagsOperationMappingInputModel,
)
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit


async def _collect(gen) -> list:
    """Drain an async generator into a list."""
    result = []
    async for item in gen:
        result.append(item)
    return result


def _make_abs_path(handler_svc: ResourceHandlerService, fs_path: str) -> AbsolutePath:
    handler = handler_svc.get_handler("Test-category")
    return AbsolutePath.from_existing_path(
        path=fs_path, category="Test-category", handler=handler,
    )

# -----------------------------------------------------------------------
# ---------------------- constructBatchOperationStatus --------------------
# -----------------------------------------------------------------------

def test_construct_status_with_result(batch_svc):
    status = batch_svc.constructBatchOperationStatus(
        resultType=BatchResultType.Success, message="done",
    )
    assert status.result_type == BatchResultType.Success
    assert status.message == "done"
    assert status.status is None


def test_construct_status_progress_only(batch_svc):
    status = batch_svc.constructBatchOperationStatus(status="scanning")
    assert status.result_type is None
    assert status.status == "scanning"


# -----------------------------------------------------------------------
# ---------------------- batch_delete by IDs -----------------------------
# -----------------------------------------------------------------------

async def test_batch_delete_by_ids_removes_from_db_and_disk(
    batch_svc, init_db, video_factory, local_resource_handler_service,
    local_resource_dir: Path, fs_settings,
):
    video = await video_factory(
        name="movie_a",
        path="Test-category/Test-resource/movie_a.mp4",
    )
    assert (local_resource_dir / "movie_a.mp4").exists()

    dir_path = _make_abs_path(
        local_resource_handler_service,
        str(local_resource_dir).replace("\\", "/"),
    )
    events = await _collect(
        batch_svc.batch_delete(
            dir_path=dir_path,
            videoIds=[str(video.id)],
            fileEntries=None,
        )
    )

    # Video removed from DB.
    assert await VideoModel.get(video.id) is None
    # File removed from disk.
    assert not (local_resource_dir / "movie_a.mp4").exists()
    # Should yield at least a progress + final status.
    assert len(events) >= 2
    final = events[-1]
    assert final.result_type is not None
    assert final.result_type == BatchResultType.Success


async def test_batch_delete_updates_tag_counts(
    batch_svc, init_db, video_factory, tag_factory,
    local_resource_handler_service, local_resource_dir, fs_settings,
):
    await tag_factory(name="action", tag_count=2)
    video = await video_factory(
        name="movie_b",
        path="Test-category/Test-resource/movie_b.mp4",
        tags=["action"],
    )

    dir_path = _make_abs_path(
        local_resource_handler_service,
        str(local_resource_dir).replace("\\", "/"),
    )
    await _collect(
        batch_svc.batch_delete(dir_path, [str(video.id)], None)
    )

    tag = await VideoTagModel.find_one({"name": "action"})
    assert tag.tag_count == 1


# -----------------------------------------------------------------------
# ---------------------- batch_update by IDs -----------------------------
# -----------------------------------------------------------------------

async def test_batch_update_sets_author_and_tags(
    batch_svc, init_db, video_factory, fs_settings,
):
    v = await video_factory(name="movie_a", tags=[])

    events = await _collect(
        batch_svc.batch_update(
            category="Test-category",
            videoIDs=[str(v.id)],
            fileEntries=None,
            author="alice",
            tagsOperation=TagsOperationMappingInputModel(append=True, tags=["new"]),
        )
    )

    refreshed = await VideoModel.get(v.id)
    assert refreshed.author == "alice"
    assert "new" in refreshed.tags
    assert len(events) >= 2

    tag = await VideoTagModel.find_one({"name": "new"})
    assert tag is not None and tag.tag_count == 1


async def test_batch_update_clears_series(
    batch_svc, init_db, video_factory, fs_settings,
):
    v = await video_factory(name="ep", seriesName="S", seriesOrder=1)

    await _collect(
        batch_svc.batch_update(
            category="Test-category",
            videoIDs=[str(v.id)],
            fileEntries=None,
            author=None,
            tagsOperation=TagsOperationMappingInputModel(append=True, tags=[]),
            seriesOperation=SeriesOperationInputModel(clear=True),
        )
    )

    refreshed = await VideoModel.get(v.id)
    assert refreshed.seriesName is None
    assert refreshed.seriesOrder is None


async def test_batch_update_assigns_series_with_orders(
    batch_svc, init_db, video_factory, fs_settings,
):
    a = await video_factory(name="a")
    b = await video_factory(name="b")

    await _collect(
        batch_svc.batch_update(
            category="Test-category",
            videoIDs=[str(a.id), str(b.id)],
            fileEntries=None,
            author=None,
            tagsOperation=TagsOperationMappingInputModel(append=True, tags=[]),
            seriesOperation=SeriesOperationInputModel(
                name="MySeries",
                clear=False,
                orders=[
                    SeriesOrderEntryInputModel(videoId=str(a.id), order=1),
                    SeriesOrderEntryInputModel(videoId=str(b.id), order=2),
                ],
            ),
        )
    )

    a_refreshed = await VideoModel.get(a.id)
    b_refreshed = await VideoModel.get(b.id)
    assert a_refreshed.seriesName == "MySeries"
    assert a_refreshed.seriesOrder == 1
    assert b_refreshed.seriesName == "MySeries"
    assert b_refreshed.seriesOrder == 2


async def test_batch_update_already_up_to_date(
    batch_svc, init_db, video_factory, fs_settings,
):
    v = await video_factory(name="v", author="bob", tags=["x"])

    events = await _collect(
        batch_svc.batch_update(
            category="Test-category",
            videoIDs=[str(v.id)],
            fileEntries=None,
            author="bob",
            tagsOperation=TagsOperationMappingInputModel(append=True, tags=["x"]),
        )
    )

    final = events[-1]
    assert final.result_type == BatchResultType.AlreadyUpToDate


# -----------------------------------------------------------------------
# ---------------------- batch_update by file entries ---------------------
# -----------------------------------------------------------------------

async def test_batch_update_creates_new_video_from_entry(
    batch_svc, init_db, local_resource_handler_service,
    local_resource_dir: Path, fs_settings,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    movie_a_path = str(local_resource_dir / "movie_a.mp4").replace("\\", "/")
    entry = handler.get_entry(movie_a_path)

    events = await _collect(
        batch_svc.batch_update(
            category="Test-category",
            videoIDs=None,
            fileEntries=[entry],
            author="alice",
            tagsOperation=TagsOperationMappingInputModel(append=True, tags=["new"]),
        )
    )

    db_path = handler.convert_to_DB_format_path(movie_a_path)
    video = await VideoModel.find_one({"path": db_path})
    assert video is not None
    assert video.author == "alice"
    assert "new" in video.tags
    assert video.size == 100.0

    # The insert payload must use the "_id" alias, not add a second "id" key.
    raw = await VideoModel.get_pymongo_collection().find_one({"path": db_path})
    assert "id" not in raw
    assert raw["_id"] is not None


# -----------------------------------------------------------------------
# ---------------------- batch_delete empty input ------------------------
# -----------------------------------------------------------------------

async def test_batch_delete_empty_ids_yields_failure(
    batch_svc, init_db, local_resource_handler_service, local_resource_dir, fs_settings,
):
    dir_path = _make_abs_path(
        local_resource_handler_service,
        str(local_resource_dir).replace("\\", "/"),
    )
    events = await _collect(
        batch_svc.batch_delete(dir_path, videoIds=[], fileEntries=None)
    )
    assert any(
        e.result_type == BatchResultType.Failure
        for e in events
    )


# -----------------------------------------------------------------------
# ---------------------- batch_delete by file entries --------------------
# -----------------------------------------------------------------------

async def test_batch_delete_by_file_entries_removes_from_db_and_disk(
    batch_svc, init_db, video_factory, local_resource_handler_service,
    local_resource_dir: Path, fs_settings,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    fs_path = str(local_resource_dir / "movie_a.mp4").replace("\\", "/")
    db_path = handler.convert_to_DB_format_path(fs_path)

    await video_factory(name="movie_a", path=db_path)
    assert (local_resource_dir / "movie_a.mp4").exists()

    entry = handler.get_entry(fs_path)
    dir_path = _make_abs_path(
        local_resource_handler_service,
        str(local_resource_dir).replace("\\", "/"),
    )

    events = await _collect(
        batch_svc.batch_delete(dir_path=dir_path, videoIds=None, fileEntries=[entry])
    )

    assert await VideoModel.find_one({"path": db_path}) is None
    assert not (local_resource_dir / "movie_a.mp4").exists()
    assert len(events) >= 2
    final = events[-1]
    assert final.result_type is not None


# -----------------------------------------------------------------------
# ---------------------- batch_update empty input -----------------------
# -----------------------------------------------------------------------

async def test_batch_update_empty_input_yields_failure(batch_svc, init_db, fs_settings):
    events = await _collect(
        batch_svc.batch_update(
            category="Test-category",
            videoIDs=None,
            fileEntries=None,
            author=None,
            tagsOperation=None,
        )
    )
    assert len(events) == 1
    assert events[0].result_type == BatchResultType.Failure


# -----------------------------------------------------------------------
# ---------------------- batch_update remove tags -----------------------
# -----------------------------------------------------------------------

async def test_batch_update_removes_tags_append_false(
    batch_svc, init_db, video_factory, tag_factory, fs_settings,
):
    await tag_factory(name="keep", tag_count=1)
    await tag_factory(name="remove", tag_count=1)
    v = await video_factory(name="v", tags=["keep", "remove"])

    events = await _collect(
        batch_svc.batch_update(
            category="Test-category",
            videoIDs=[str(v.id)],
            fileEntries=None,
            author=None,
            tagsOperation=TagsOperationMappingInputModel(append=False, tags=["remove"]),
        )
    )

    refreshed = await VideoModel.get(v.id)
    assert "remove" not in refreshed.tags
    assert "keep" in refreshed.tags
    assert len(events) >= 2

    removed_tag = await VideoTagModel.find_one({"name": "remove"})
    assert removed_tag is None


# -----------------------------------------------------------------------
# ------------ batch_update fetches duration when zero ------------------
# -----------------------------------------------------------------------

async def test_batch_update_fetches_duration_when_zero(
    batch_svc, init_db, video_factory, fs_settings,
):
    v = await video_factory(name="movie_a", duration=0.0)

    events = await _collect(
        batch_svc.batch_update(
            category="Test-category",
            videoIDs=[str(v.id)],
            fileEntries=None,
            author="alice",
            tagsOperation=TagsOperationMappingInputModel(append=True, tags=[]),
        )
    )

    refreshed = await VideoModel.get(v.id)
    assert refreshed.duration == 120.0
    assert refreshed.author == "alice"
