"""Unit tests for BrowseFileService — directory listing, video browsing, and sorting."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.features.catalog.video import VideoModel
from src.features.browsing.browse_file_service import DirectoryEntry, VideoEntry
from src.errors import FileBrowseError
from src.platform.storage.absolute_path import AbsolutePath

pytestmark = pytest.mark.unit


def _entry_name(entry) -> str:
    """Display name of a listing row, whichever kind it is."""
    return entry.name if isinstance(entry, DirectoryEntry) else entry.document.name


# -----------------------------------------------------------------------
# ------------------- Root level listing ---------------------------------
# -----------------------------------------------------------------------

async def test_root_level_lists_categories(browse_svc, init_db):
    abs_path = AbsolutePath(abs_path=None, category=None, handler=None)
    nodes = await browse_svc.get_node_list_in_directory(abs_path)

    names = [_entry_name(n) for n in nodes]
    assert "Test-category" in names
    assert all(isinstance(n, DirectoryEntry) for n in nodes)


# -----------------------------------------------------------------------
# ------------------- Category level listing -----------------------------
# -----------------------------------------------------------------------

async def test_category_level_lists_pseudo_names(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    abs_path = AbsolutePath.from_existing_path(
        path="Test-category", category="Test-category", handler=handler,
    )
    nodes = await browse_svc.get_node_list_in_directory(abs_path)

    names = [_entry_name(n) for n in nodes]
    assert "Test-resource" in names


# -----------------------------------------------------------------------
# ------------------- Directory level listing ----------------------------
# -----------------------------------------------------------------------

async def test_directory_level_discovers_videos_and_subdirs(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    nodes = await browse_svc.get_node_list_in_directory(abs_path)
    names = [_entry_name(n) for n in nodes]

    # Should find movie_a, movie_b (videos) and subdir (directory).
    # notes.txt is not a video, skipped. empty/ has 0 size → skipped.
    assert "movie_a" in names
    assert "movie_b" in names
    assert "subdir" in names
    assert "notes" not in names


async def test_directory_level_inserts_video_model_on_first_browse(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    await browse_svc.get_node_list_in_directory(abs_path)

    # Videos should now exist in the database.
    db_path = handler.convert_to_DB_format_path(
        str(local_resource_dir / "movie_a.mp4").replace("\\", "/")
    )
    video = await VideoModel.find_one({"path": db_path})
    assert video is not None
    assert video.name == "movie_a"
    assert video.size == 100.0
    assert video.category == "Test-category"


async def test_directory_level_does_not_duplicate_on_rebrowse(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    await browse_svc.get_node_list_in_directory(abs_path)
    await browse_svc.get_node_list_in_directory(abs_path)

    all_videos = await VideoModel.find({"category": "Test-category"}).to_list()
    paths = [v.path for v in all_videos]
    assert len(paths) == len(set(paths))  # no duplicates


async def test_inserted_documents_carry_no_stray_id_field(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir,
):
    """The insert payload must use the ``_id`` alias, not a second ``id`` key."""
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    await browse_svc.get_node_list_in_directory(abs_path)

    raw = await VideoModel.get_pymongo_collection().find_one({"name": "movie_a"})
    assert raw is not None
    assert "id" not in raw
    assert raw["_id"] is not None


# -----------------------------------------------------------------------
# ------------------- Batched duration resolution ------------------------
# -----------------------------------------------------------------------

async def test_duration_probed_once_per_new_file(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir, ffmpeg_svc,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    await browse_svc.get_node_list_in_directory(abs_path)

    # movie_a and movie_b only — subdir is a directory, notes.txt is not a video.
    assert ffmpeg_svc.get_video_duration.await_count == 2

    videos = await VideoModel.find({"category": "Test-category"}).to_list()
    assert {v.name for v in videos} == {"movie_a", "movie_b"}
    assert all(v.duration == 120.0 for v in videos)


async def test_duration_not_reprobed_for_known_files(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir, ffmpeg_svc,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    await browse_svc.get_node_list_in_directory(abs_path)
    ffmpeg_svc.get_video_duration.reset_mock()

    # Second browse: both documents already carry a duration, so ffprobe stays idle.
    await browse_svc.get_node_list_in_directory(abs_path)
    ffmpeg_svc.get_video_duration.assert_not_awaited()


async def test_zero_duration_is_backfilled_on_browse(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir, ffmpeg_svc,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    await browse_svc.get_node_list_in_directory(abs_path)

    # Knock one document's duration back to 0, as an interrupted probe would leave it.
    stale = await VideoModel.find_one({"name": "movie_a"})
    stale.duration = 0.0
    await stale.save()

    ffmpeg_svc.get_video_duration.reset_mock()
    ffmpeg_svc.get_video_duration.return_value = 42.0
    nodes = await browse_svc.get_node_list_in_directory(abs_path)

    # Only the stale one is re-probed, and the new value is both returned and persisted.
    assert ffmpeg_svc.get_video_duration.await_count == 1
    refreshed = await VideoModel.find_one({"name": "movie_a"})
    assert refreshed.duration == 42.0
    assert next(
        n.document.duration for n in nodes
        if isinstance(n, VideoEntry) and n.document.name == "movie_a"
    ) == 42.0


async def test_directories_lead_the_listing_then_video_files(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir,
):
    """Videos are resolved as one batch, so they trail the sub-directories."""
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    nodes = await browse_svc.get_node_list_in_directory(abs_path)
    names = [_entry_name(n) for n in nodes]

    assert names == ["subdir", "movie_a", "movie_b"]


# -----------------------------------------------------------------------
# ------------------- get_all_video_entries_in_directory ------------------
# -----------------------------------------------------------------------

def test_get_all_video_entries_recursive(
    browse_svc, local_resource_handler_service, local_resource_dir: Path,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")

    entries = browse_svc.get_all_video_entries_in_directory(root_fs, "Test-category")
    names = sorted(e.name for e in entries)

    assert names == ["movie_a.mp4", "movie_b.mp4", "movie_c.mp4"]


def test_get_all_video_entries_empty_dir(
    browse_svc, local_resource_handler_service, local_resource_dir: Path,
):
    empty = str(local_resource_dir / "subdir" / "empty").replace("\\", "/")
    entries = browse_svc.get_all_video_entries_in_directory(empty, "Test-category")
    assert entries == []


# -----------------------------------------------------------------------
# ------------------- Error paths ----------------------------------------
# -----------------------------------------------------------------------

def test_get_all_video_entries_os_error_returns_empty(
    browse_svc, local_resource_handler_service,
):
    entries = browse_svc.get_all_video_entries_in_directory(
        "Z:/nonexistent/path", "Test-category",
    )
    assert entries == []


async def test_directory_level_general_exception_raises_file_browse_error(
    browse_svc, init_db, local_resource_handler_service,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    abs_path = AbsolutePath.from_existing_path(
        path="Z:/nonexistent/directory",
        category="Test-category",
        handler=handler,
    )
    with pytest.raises(FileBrowseError):
        await browse_svc.get_node_list_in_directory(abs_path)
