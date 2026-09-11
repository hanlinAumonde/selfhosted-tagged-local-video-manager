"""
Behaviour specification — remembering that a directory was created by a user.

A directory holding no video aggregates to ``(0.0, 0.0)``, and the browser hides rows
that report that, which is why a freshly created folder would vanish the moment it was
made. "Has a dir_metadata record" cannot tell the two apart either:
``calculate_directory_metadata`` persists a record for *every* directory it walks,
zeros included — so an incidental empty folder has one too.

The fact that cannot be derived from the filesystem is therefore stored explicitly:
``user_created``. These tests pin it down, and pin down that recalculating metadata —
which rewrites size and mtime on the same document — must not wipe it.
"""

from pathlib import Path

import pytest

from src.features.browsing.dir_metadata import DirMetadataModel
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


# -----------------------------------------------------------------------
# ---------------------- Marking and reading the flag --------------------
# -----------------------------------------------------------------------

async def test_directory_is_not_user_created_by_default(dir_svc, init_db):
    db_path = f"{CATEGORY}/Test-resource/subdir"
    await dir_svc.set_metadata(CATEGORY, db_path, 300.0, 1700000000.0)

    assert await dir_svc.is_user_created(CATEGORY, db_path) is False


async def test_marking_a_directory_records_it_as_user_created(dir_svc, init_db):
    db_path = f"{CATEGORY}/Test-resource/brand_new"
    assert await DirMetadataModel.find_one({"path": db_path}) is None

    await dir_svc.mark_user_created(CATEGORY, db_path)

    assert await DirMetadataModel.find_one({"path": db_path}) is not None
    assert await dir_svc.is_user_created(CATEGORY, db_path) is True


async def test_marking_is_idempotent(dir_svc, init_db):
    db_path = f"{CATEGORY}/Test-resource/brand_new"
    await dir_svc.mark_user_created(CATEGORY, db_path)

    await dir_svc.mark_user_created(CATEGORY, db_path)

    assert await DirMetadataModel.find({"path": db_path}).count() == 1
    assert await dir_svc.is_user_created(CATEGORY, db_path) is True


# -----------------------------------------------------------------------
# ---------------------- Surviving a recalculation -----------------------
# -----------------------------------------------------------------------

async def test_recalculating_metadata_keeps_the_user_created_flag(
    dir_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    empty_dir = local_resource_dir / "subdir" / "empty"
    abs_path = _abs_path(local_resource_handler_service, empty_dir)
    await dir_svc.mark_user_created(CATEGORY, abs_path.DB_format_path())

    size, mtime = await dir_svc.calculate_directory_metadata(abs_path, skipCache=True)
    assert (size, mtime) == (0.0, 0.0)

    assert await dir_svc.is_user_created(CATEGORY, abs_path.DB_format_path()) is True


async def test_marking_does_not_overwrite_existing_size_and_mtime(dir_svc, init_db):
    db_path = f"{CATEGORY}/Test-resource/subdir"
    await dir_svc.set_metadata(CATEGORY, db_path, 300.0, 1700000000.0)

    await dir_svc.mark_user_created(CATEGORY, db_path)

    doc = await DirMetadataModel.find_one({"path": db_path})
    assert (doc.total_size, doc.last_modified_time) == (300.0, 1700000000.0)
