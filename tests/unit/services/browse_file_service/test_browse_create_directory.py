"""
Behaviour specification — creating a directory, and keeping it visible while empty.

Two halves of one feature:

* ``create_directory`` makes the directory on the storage behind the category and
  records it as user-created, so the next listing has something to go on.
* ``_get_directory_node`` stops hiding a zero-size directory when that record says a
  user made it. Incidental empty directories — a folder of non-video files, a stray
  empty directory on disk — stay hidden, which is the behaviour that filter exists for.

Where creation is refused matters as much as where it works: the root and category
levels are not real directories (they list configured categories and mount points), and
a name carrying a path separator would let a caller write outside the directory shown.
"""

from pathlib import Path

import pytest

from src.config import Settings
from src.errors import InputValidationError
from src.features.browsing.browse_file_service import DirectoryEntry
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit

CATEGORY = "Test-category"


def _abs_path(handler_svc: ResourceHandlerService, directory: Path) -> AbsolutePath:
    return AbsolutePath.from_existing_path(
        path=str(directory).replace("\\", "/"),
        category=CATEGORY,
        handler=handler_svc.get_handler(CATEGORY),
    )


def _entry_name(entry) -> str:
    """Display name of a listing row, whichever kind it is."""
    return entry.name if isinstance(entry, DirectoryEntry) else entry.document.name


def _directory_entry(nodes, name: str) -> DirectoryEntry | None:
    for node in nodes:
        if isinstance(node, DirectoryEntry) and node.name == name:
            return node
    return None


# -----------------------------------------------------------------------
# ---------------------------- Creating ----------------------------------
# -----------------------------------------------------------------------

async def test_create_directory_creates_it_under_the_given_parent(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    parent = _abs_path(local_resource_handler_service, local_resource_dir)

    await browse_svc.create_directory(parent, "new_folder")

    assert (local_resource_dir / "new_folder").is_dir()


async def test_create_directory_records_it_as_user_created(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    parent = _abs_path(local_resource_handler_service, local_resource_dir)

    await browse_svc.create_directory(parent, "new_folder")

    assert await browse_svc.dirMetadataService.is_user_created(
        CATEGORY, f"{CATEGORY}/Test-resource/new_folder"
    ) is True


async def test_create_directory_returns_the_new_db_path(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    parent = _abs_path(local_resource_handler_service, local_resource_dir)

    db_path = await browse_svc.create_directory(parent, "new_folder")

    assert db_path == f"{CATEGORY}/Test-resource/new_folder"


# -----------------------------------------------------------------------
# ---------------------------- Refusals ----------------------------------
# -----------------------------------------------------------------------

async def test_create_directory_is_refused_at_root_level(browse_svc, init_db):
    root = AbsolutePath.from_relative_path(parsedPath=None)

    with pytest.raises(InputValidationError):
        await browse_svc.create_directory(root, "new_folder")


async def test_create_directory_is_refused_at_category_level(
    browse_svc, init_db, local_resource_handler_service, fs_settings: Settings,
):
    category_level = AbsolutePath.from_relative_path(
        parsedPath=(CATEGORY, None, None),
        handlerService=local_resource_handler_service,
        settings=fs_settings,
    )

    with pytest.raises(InputValidationError):
        await browse_svc.create_directory(category_level, "new_folder")


async def test_create_directory_is_refused_when_the_name_is_already_taken(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    parent = _abs_path(local_resource_handler_service, local_resource_dir)

    with pytest.raises(InputValidationError):
        await browse_svc.create_directory(parent, "subdir")

    assert (local_resource_dir / "subdir" / "movie_c.mp4").is_file()


async def test_create_directory_is_refused_when_the_name_contains_a_separator(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    parent = _abs_path(local_resource_handler_service, local_resource_dir)

    with pytest.raises(InputValidationError):
        await browse_svc.create_directory(parent, "outer/inner")

    assert not (local_resource_dir / "outer").exists()


async def test_create_directory_is_refused_when_the_name_is_a_parent_reference(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    parent = _abs_path(local_resource_handler_service, local_resource_dir)

    with pytest.raises(InputValidationError):
        await browse_svc.create_directory(parent, "..")


async def test_create_directory_is_refused_when_the_name_is_blank(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    parent = _abs_path(local_resource_handler_service, local_resource_dir)

    with pytest.raises(InputValidationError):
        await browse_svc.create_directory(parent, "   ")


# -----------------------------------------------------------------------
# ---------------- Listing an empty directory afterwards -----------------
# -----------------------------------------------------------------------

async def test_a_user_created_empty_directory_is_listed(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    parent = _abs_path(local_resource_handler_service, local_resource_dir)
    await browse_svc.create_directory(parent, "new_folder")

    nodes = await browse_svc.get_node_list_in_directory(parent)

    assert "new_folder" in [_entry_name(n) for n in nodes]


async def test_an_incidental_empty_directory_is_still_hidden(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    subdir = local_resource_dir / "subdir"
    assert (subdir / "empty").is_dir()

    nodes = await browse_svc.get_node_list_in_directory(
        _abs_path(local_resource_handler_service, subdir)
    )

    assert "empty" not in [_entry_name(n) for n in nodes]


async def test_a_directory_holding_only_non_video_files_is_still_hidden(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    docs_dir = local_resource_dir / "docs"
    docs_dir.mkdir()
    (docs_dir / "readme.txt").write_text("no videos here")

    nodes = await browse_svc.get_node_list_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir)
    )

    assert "docs" not in [_entry_name(n) for n in nodes]


async def test_a_user_created_directory_lists_normally_once_it_holds_a_video(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    parent = _abs_path(local_resource_handler_service, local_resource_dir)
    await browse_svc.create_directory(parent, "new_folder")
    (local_resource_dir / "new_folder" / "movie_d.mp4").write_bytes(b"d" * 150)

    nodes = await browse_svc.get_node_list_in_directory(parent, skipCache=True)

    entry = _directory_entry(nodes, "new_folder")
    assert entry is not None
    assert entry.size == 150.0
    assert entry.last_modify_time > 0.0
