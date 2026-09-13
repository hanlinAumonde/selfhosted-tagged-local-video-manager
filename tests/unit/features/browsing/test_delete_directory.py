"""
Behaviour specification — "Delete all" on a directory row.

The old menu item emptied a directory of videos and left the directory itself standing.
That is one of two things a user can mean, and the folder's fate afterwards was decided
by an accident: a directory with no videos aggregates to zero and the browser hides
zero-aggregate rows, so a folder someone deliberately kept would vanish anyway unless it
happened to be marked ``user_created``.

So the choice is now asked for, and each answer is recorded as a fact the filesystem
cannot supply:

* **Keep the folder** — the videos go, the folder stays listed. It has nothing in it, so
  the only thing that can keep it visible is ``user_created``.
* **Delete the folder too** — the folder stops being listed. Whether it also leaves the
  storage depends on what is left behind: a directory holding nothing else is removed
  outright, while one still holding other files or sub-directories is left exactly where
  it is and marked ``user_deleted``. Deleting never recurses over the storage — the
  videos underneath are removed because the batch delete already walks the tree, but not
  one directory in that tree is unlinked.

``user_deleted`` is a hiding rule with a second job: it is what makes re-creating the
same folder later a matter of clearing a flag rather than a ``FileExistsError`` over a
directory that never actually left.
"""

from pathlib import Path

import pytest

from src.config import Settings
from src.errors import InputValidationError
from src.features.browsing.batch_operation_service import DirectoryDeletionStrategy
from src.features.browsing.browse_file_service import DirectoryEntry
from src.features.browsing.dir_metadata import DirMetadataModel
from src.features.catalog.video import VideoModel
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit

CATEGORY = "Test-category"


# -----------------------------------------------------------------------
# ------------------------------ Helpers ---------------------------------
# -----------------------------------------------------------------------

async def _collect(gen) -> list:
    return [item async for item in gen]


def _abs(handler_svc: ResourceHandlerService, path: Path) -> AbsolutePath:
    return AbsolutePath.from_existing_path(
        path=str(path).replace("\\", "/"),
        category=CATEGORY,
        handler=handler_svc.get_handler(CATEGORY),
    )


def _db(handler_svc: ResourceHandlerService, path: Path) -> str:
    handler = handler_svc.get_handler(CATEGORY)
    return handler.convert_to_DB_format_path(str(path).replace("\\", "/"))


async def _seed(video_factory, handler_svc: ResourceHandlerService, *paths: Path) -> None:
    """Give each video file on disk the document a browse would have created."""
    for path in paths:
        await video_factory(name=path.stem, path=_db(handler_svc, path))


def _video(directory: Path, name: str, size: int = 100) -> Path:
    path = directory / name
    path.write_bytes(b"v" * size)
    return path


async def _delete_all(
    batch_svc, browse_svc, handler_svc: ResourceHandlerService,
    directory: Path, strategy: DirectoryDeletionStrategy,
) -> list:
    """Run a delete-all over a directory the way the subscription resolver does."""
    entries = browse_svc.get_all_video_entries_in_directory(
        str(directory).replace("\\", "/"), CATEGORY
    )
    return await _collect(
        batch_svc.batch_delete(
            dir_path=_abs(handler_svc, directory),
            videoIds=None,
            fileEntries=entries,
            directoryDeletion=strategy,
        )
    )


def _listed_names(nodes) -> list[str]:
    return [n.name for n in nodes if isinstance(n, DirectoryEntry)]


# -----------------------------------------------------------------------
# --------------------- Keeping the folder -------------------------------
# -----------------------------------------------------------------------

async def test_keeping_the_folder_deletes_every_video_under_it(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    nested = target / "nested"
    nested.mkdir()
    top = _video(target, "movie_1.mp4")
    deep = _video(nested, "movie_2.mp4")
    await _seed(video_factory, local_resource_handler_service, top, deep)

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.KeepFolder,
    )

    assert not top.exists()
    assert not deep.exists()
    assert await VideoModel.find({"category": CATEGORY}).count() == 0


async def test_keeping_the_folder_leaves_the_directory_on_the_storage(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    await _seed(video_factory, local_resource_handler_service, _video(target, "movie_1.mp4"))

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.KeepFolder,
    )

    assert target.is_dir()


async def test_a_kept_folder_is_marked_user_created_so_it_stays_listed(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    await _seed(video_factory, local_resource_handler_service, _video(target, "movie_1.mp4"))

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.KeepFolder,
    )

    assert await browse_svc.dirMetadataService.is_user_created(
        CATEGORY, _db(local_resource_handler_service, target)
    ) is True

    nodes = await browse_svc.get_node_list_in_directory(
        _abs(local_resource_handler_service, local_resource_dir), skipCache=True
    )
    assert "target" in _listed_names(nodes)


async def test_keeping_the_folder_leaves_sub_directories_on_the_storage(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    nested = target / "nested"
    nested.mkdir()
    deep = _video(nested, "movie_2.mp4")
    await _seed(video_factory, local_resource_handler_service, deep)

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.KeepFolder,
    )

    assert target.is_dir()
    assert nested.is_dir()
    assert not deep.exists()


# -----------------------------------------------------------------------
# ------------- Deleting the folder — nothing else inside ----------------
# -----------------------------------------------------------------------

async def test_deleting_a_folder_that_held_only_videos_removes_it_from_the_storage(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    await _seed(
        video_factory, local_resource_handler_service,
        _video(target, "movie_1.mp4"), _video(target, "movie_2.mp4"),
    )

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.DeleteFolder,
    )

    assert not target.exists()


async def test_a_removed_folder_leaves_no_directory_metadata_behind(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    await _seed(video_factory, local_resource_handler_service, _video(target, "movie_1.mp4"))
    db_path = _db(local_resource_handler_service, target)
    # A browse records metadata for every directory it walks, this one included.
    await browse_svc.get_node_list_in_directory(
        _abs(local_resource_handler_service, local_resource_dir), skipCache=True
    )
    assert await DirMetadataModel.find_one({"path": db_path}) is not None

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.DeleteFolder,
    )

    assert await DirMetadataModel.find_one({"path": db_path}) is None


async def test_a_removed_folder_is_gone_from_the_listing(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    await _seed(video_factory, local_resource_handler_service, _video(target, "movie_1.mp4"))

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.DeleteFolder,
    )

    nodes = await browse_svc.get_node_list_in_directory(
        _abs(local_resource_handler_service, local_resource_dir), skipCache=True
    )
    assert "target" not in _listed_names(nodes)


async def test_an_empty_folder_can_be_deleted_even_though_it_holds_no_videos(
    batch_svc, browse_svc, init_db,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    """A folder someone made and never filled is exactly the one they want to take back."""
    parent = _abs(local_resource_handler_service, local_resource_dir)
    await browse_svc.create_directory(parent, "target")
    target = local_resource_dir / "target"

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.DeleteFolder,
    )

    assert not target.exists()


# -----------------------------------------------------------------------
# -------------- Deleting the folder — something else inside -------------
# -----------------------------------------------------------------------

async def test_a_folder_still_holding_other_files_is_left_on_the_storage(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    movie = _video(target, "movie_1.mp4")
    subtitle = target / "movie_1.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
    await _seed(video_factory, local_resource_handler_service, movie)

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.DeleteFolder,
    )

    assert not movie.exists()
    assert target.is_dir()
    assert subtitle.is_file()


async def test_a_folder_still_holding_other_files_is_marked_user_deleted(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    (target / "movie_1.srt").write_text("subtitle")
    await _seed(video_factory, local_resource_handler_service, _video(target, "movie_1.mp4"))

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.DeleteFolder,
    )

    assert await browse_svc.dirMetadataService.is_user_deleted(
        CATEGORY, _db(local_resource_handler_service, target)
    ) is True


async def test_a_folder_still_holding_a_sub_directory_is_left_on_the_storage(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    nested = target / "nested"
    nested.mkdir()
    top = _video(target, "movie_1.mp4")
    deep = _video(nested, "movie_2.mp4")
    await _seed(video_factory, local_resource_handler_service, top, deep)

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.DeleteFolder,
    )

    assert not top.exists()
    assert not deep.exists()
    assert target.is_dir()
    assert nested.is_dir()
    assert await browse_svc.dirMetadataService.is_user_deleted(
        CATEGORY, _db(local_resource_handler_service, target)
    ) is True


async def test_a_user_created_folder_that_is_deleted_stops_being_user_created(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    parent = _abs(local_resource_handler_service, local_resource_dir)
    await browse_svc.create_directory(parent, "target")
    target = local_resource_dir / "target"
    (target / "movie_1.srt").write_text("subtitle")
    await _seed(video_factory, local_resource_handler_service, _video(target, "movie_1.mp4"))

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.DeleteFolder,
    )

    db_path = _db(local_resource_handler_service, target)
    assert await browse_svc.dirMetadataService.is_user_created(CATEGORY, db_path) is False


# -----------------------------------------------------------------------
# --------------- What a user_deleted directory looks like ---------------
# -----------------------------------------------------------------------

async def test_a_user_deleted_directory_is_absent_from_the_listing(
    browse_svc, init_db,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    (target / "readme.txt").write_text("not a video")
    await browse_svc.dirMetadataService.mark_user_deleted(
        CATEGORY, _db(local_resource_handler_service, target)
    )

    nodes = await browse_svc.get_node_list_in_directory(
        _abs(local_resource_handler_service, local_resource_dir), skipCache=True
    )

    assert "target" not in _listed_names(nodes)


async def test_a_user_deleted_directory_stays_hidden_even_if_it_aggregates_above_zero(
    browse_svc, init_db,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    """A part-failed delete must not make the row reappear as if nothing happened."""
    target = local_resource_dir / "target"
    target.mkdir()
    _video(target, "survivor.mp4")
    await browse_svc.dirMetadataService.mark_user_deleted(
        CATEGORY, _db(local_resource_handler_service, target)
    )

    nodes = await browse_svc.get_node_list_in_directory(
        _abs(local_resource_handler_service, local_resource_dir), skipCache=True
    )

    assert "target" not in _listed_names(nodes)


# -----------------------------------------------------------------------
# ------------------- Re-creating a deleted folder -----------------------
# -----------------------------------------------------------------------

async def test_creating_a_folder_over_a_user_deleted_one_succeeds(
    browse_svc, init_db,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    (target / "readme.txt").write_text("not a video")
    await browse_svc.dirMetadataService.mark_user_deleted(
        CATEGORY, _db(local_resource_handler_service, target)
    )

    db_path = await browse_svc.create_directory(
        _abs(local_resource_handler_service, local_resource_dir), "target"
    )

    assert db_path == _db(local_resource_handler_service, target)


async def test_re_creating_a_deleted_folder_clears_the_user_deleted_mark(
    browse_svc, init_db,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    (target / "readme.txt").write_text("not a video")
    db_path = _db(local_resource_handler_service, target)
    await browse_svc.dirMetadataService.mark_user_deleted(CATEGORY, db_path)

    await browse_svc.create_directory(
        _abs(local_resource_handler_service, local_resource_dir), "target"
    )

    assert await browse_svc.dirMetadataService.is_user_deleted(CATEGORY, db_path) is False
    assert await browse_svc.dirMetadataService.is_user_created(CATEGORY, db_path) is True

    nodes = await browse_svc.get_node_list_in_directory(
        _abs(local_resource_handler_service, local_resource_dir), skipCache=True
    )
    assert "target" in _listed_names(nodes)


async def test_re_creating_a_deleted_folder_touches_nothing_on_the_storage(
    browse_svc, init_db,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    leftover = target / "readme.txt"
    leftover.write_text("not a video")
    await browse_svc.dirMetadataService.mark_user_deleted(
        CATEGORY, _db(local_resource_handler_service, target)
    )

    await browse_svc.create_directory(
        _abs(local_resource_handler_service, local_resource_dir), "target"
    )

    assert leftover.read_text() == "not a video"


async def test_creating_a_folder_over_a_directory_nobody_deleted_is_still_refused(
    browse_svc, init_db,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()

    with pytest.raises(InputValidationError):
        await browse_svc.create_directory(
            _abs(local_resource_handler_service, local_resource_dir), "target"
        )


# -----------------------------------------------------------------------
# ------------------------- Refusals and edges ---------------------------
# -----------------------------------------------------------------------

async def test_deleting_the_folder_is_refused_at_the_category_level(
    batch_svc, init_db, local_resource_handler_service, fs_settings: Settings,
):
    category_level = AbsolutePath.from_relative_path(
        parsedPath=(CATEGORY, None, None),
        handlerService=local_resource_handler_service,
        settings=fs_settings,
    )

    with pytest.raises(InputValidationError):
        await _collect(
            batch_svc.batch_delete(
                dir_path=category_level,
                videoIds=None,
                fileEntries=[],
                directoryDeletion=DirectoryDeletionStrategy.DeleteFolder,
            )
        )


async def test_the_parent_s_metadata_is_recalculated_after_the_folder_goes(
    batch_svc, browse_svc, init_db, video_factory,
    local_resource_handler_service, local_resource_dir: Path, fs_settings: Settings,
):
    target = local_resource_dir / "target"
    target.mkdir()
    await _seed(
        video_factory, local_resource_handler_service,
        _video(target, "movie_1.mp4", size=500),
    )
    parent = _abs(local_resource_handler_service, local_resource_dir)
    # The fixture tree holds 100 + 200 + 300 bytes of video before "target" is added.
    await browse_svc.get_node_list_in_directory(parent, skipCache=True)

    await _delete_all(
        batch_svc, browse_svc, local_resource_handler_service,
        target, DirectoryDeletionStrategy.DeleteFolder,
    )

    total_size, _ = await browse_svc.dirMetadataService.get_metadata(
        CATEGORY, _db(local_resource_handler_service, local_resource_dir)
    )
    assert total_size == 600.0
