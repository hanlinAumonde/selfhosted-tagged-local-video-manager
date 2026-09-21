"""
Browsing a directory that an active migration is writing into.

A migration copies bytes to its target path long before the catalog record moves
there. Browsing that directory meanwhile used to hand the half-written file to
the normal "new file on disk" path, which inserted a document at the target path;
the migration then reached UPDATING_DB, tried to move its own record onto that
same path, and hit the unique index on `path` with a DuplicateKeyError.

The rule under test: a file on disk that has no catalog document and is held by
an active migration is not a video yet — it is neither inserted nor listed.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.features.catalog.video import VideoModel
from src.features.browsing.browse_file_service import DirectoryEntry, VideoEntry
from src.platform.jobs.task_model import TaskStatus
from src.platform.storage.absolute_path import AbsolutePath

pytestmark = pytest.mark.unit


def _entry_name(entry) -> str:
    """Display name of a listing row, whichever kind it is."""
    return entry.name if isinstance(entry, DirectoryEntry) else entry.document.name


def _db_path(handler, file_path: Path) -> str:
    return handler.convert_to_DB_format_path(str(file_path).replace("\\", "/"))


def _abs_path(handler, directory: Path) -> AbsolutePath:
    return AbsolutePath.from_existing_path(
        path=str(directory).replace("\\", "/"),
        category="Test-category",
        handler=handler,
    )


def _video_entry(nodes, name: str) -> VideoEntry | None:
    for node in nodes:
        if isinstance(node, VideoEntry) and node.document.name == name:
            return node
    return None


# -----------------------------------------------------------------------
# ---------- Target file, while the record has not moved yet -------------
# -----------------------------------------------------------------------

async def test_active_migration_target_is_not_inserted_into_catalog(
    browse_svc, init_db, task_factory, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    target_db_path = _db_path(handler, local_resource_dir / "movie_a.mp4")
    await task_factory(
        source_path="Other-category/Other-resource/movie_a.mp4",
        source_category="Other-category",
        target_path=target_db_path,
        target_category="Test-category",
        status=TaskStatus.PROCESSING,
    )

    await browse_svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    assert await VideoModel.find_one({"path": target_db_path}) is None


async def test_active_migration_target_is_not_listed(
    browse_svc, init_db, task_factory, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    await task_factory(
        source_path="Other-category/Other-resource/movie_a.mp4",
        source_category="Other-category",
        target_path=_db_path(handler, local_resource_dir / "movie_a.mp4"),
        target_category="Test-category",
        status=TaskStatus.PROCESSING,
    )

    nodes = await browse_svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    names = [_entry_name(n) for n in nodes]
    assert "movie_a" not in names


async def test_skipped_target_does_not_count_as_a_new_file(
    browse_svc, init_db, task_factory, local_resource_handler_service, local_resource_dir,
):
    # subdir holds exactly one video, movie_c; making it the migration target
    # leaves the directory with nothing genuinely new to report.
    handler = local_resource_handler_service.get_handler("Test-category")
    subdir = local_resource_dir / "subdir"
    await task_factory(
        source_path="Other-category/Other-resource/movie_c.mp4",
        source_category="Other-category",
        target_path=_db_path(handler, subdir / "movie_c.mp4"),
        target_category="Test-category",
        status=TaskStatus.PROCESSING,
    )

    with patch.object(
        browse_svc.dirMetadataService,
        "update_directory_metadata_forward",
        new=AsyncMock(),
    ) as forward_update:
        await browse_svc.get_node_list_in_directory(_abs_path(handler, subdir))

    forward_update.assert_not_called()


# -----------------------------------------------------------------------
# ---------- Target file, once the record has moved ----------------------
# -----------------------------------------------------------------------

async def test_target_is_listed_and_locked_once_the_record_moved(
    browse_svc, init_db, task_factory, video_factory,
    local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    target_db_path = _db_path(handler, local_resource_dir / "movie_a.mp4")
    # UPDATING_DB has already run: the record now sits at the target path.
    await video_factory(name="movie_a", path=target_db_path)
    await task_factory(
        source_path="Other-category/Other-resource/movie_a.mp4",
        source_category="Other-category",
        target_path=target_db_path,
        target_category="Test-category",
        status=TaskStatus.DB_UPDATED,
    )

    nodes = await browse_svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    entry = _video_entry(nodes, "movie_a")
    assert entry is not None
    assert entry.is_locked is True


# -----------------------------------------------------------------------
# ---------- Guards against filtering too much ---------------------------
# -----------------------------------------------------------------------

async def test_source_file_stays_listed_and_locked_during_migration(
    browse_svc, init_db, task_factory, video_factory,
    local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    source_db_path = _db_path(handler, local_resource_dir / "movie_a.mp4")
    await video_factory(name="movie_a", path=source_db_path)
    await task_factory(
        source_path=source_db_path,
        source_category="Test-category",
        target_path="Other-category/Other-resource/movie_a.mp4",
        target_category="Other-category",
        status=TaskStatus.PROCESSING,
    )

    nodes = await browse_svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    entry = _video_entry(nodes, "movie_a")
    assert entry is not None
    assert entry.is_locked is True


async def test_unrelated_new_file_in_the_same_directory_is_still_inserted(
    browse_svc, init_db, task_factory, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    await task_factory(
        source_path="Other-category/Other-resource/movie_a.mp4",
        source_category="Other-category",
        target_path=_db_path(handler, local_resource_dir / "movie_a.mp4"),
        target_category="Test-category",
        status=TaskStatus.PROCESSING,
    )

    nodes = await browse_svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    movie_b_db_path = _db_path(handler, local_resource_dir / "movie_b.mp4")
    assert await VideoModel.find_one({"path": movie_b_db_path}) is not None
    assert "movie_b" in [_entry_name(n) for n in nodes]


async def test_target_of_a_finished_migration_is_treated_as_an_ordinary_file(
    browse_svc, init_db, task_factory, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    target_db_path = _db_path(handler, local_resource_dir / "movie_a.mp4")
    await task_factory(
        source_path="Other-category/Other-resource/movie_a.mp4",
        source_category="Other-category",
        target_path=target_db_path,
        target_category="Test-category",
        status=TaskStatus.COMPLETED,
    )

    nodes = await browse_svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    assert await VideoModel.find_one({"path": target_db_path}) is not None
    assert "movie_a" in [_entry_name(n) for n in nodes]
