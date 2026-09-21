"""Unit tests for DirectoryMetadataService — get, set, and aggregate metadata."""

from pathlib import Path

import pytest

from src.platform.storage.absolute_path import AbsolutePath

pytestmark = pytest.mark.unit

# -----------------------------------------------------------------------
# ----------------------- get / set metadata -----------------------------
# -----------------------------------------------------------------------

async def test_get_metadata_returns_none_when_empty(dir_svc, init_db):
    result = await dir_svc.get_metadata("Test-category", "some/path")
    assert result is None


async def test_set_and_get_metadata_round_trip(dir_svc, init_db):
    await dir_svc.set_metadata("Test-category", "Test-category/Test-resource", 999.0, 1700000000.0)
    result = await dir_svc.get_metadata("Test-category", "Test-category/Test-resource")
    assert result == (999.0, 1700000000.0)


async def test_set_metadata_updates_cache(dir_svc, init_db, local_cache_service):
    await dir_svc.set_metadata("Test-category", "a/b", 1.0, 2.0)
    cached = local_cache_service.get("Test-category:a/b")
    assert cached == (1.0, 2.0)


async def test_get_metadata_serves_from_cache(dir_svc, init_db, local_cache_service):
    local_cache_service.set("Test-category:cached/path", (42.0, 99.0))
    result = await dir_svc.get_metadata("Test-category", "cached/path")
    assert result == (42.0, 99.0)


# -----------------------------------------------------------------------
# ----------------------- bulk_set_metadata ------------------------------
# -----------------------------------------------------------------------

async def test_bulk_set_metadata_inserts_multiple(dir_svc, init_db):
    entries = {
        "Test-category/Test-resource/a": (10.0, 1.0),
        "Test-category/Test-resource/b": (20.0, 2.0),
    }
    await dir_svc.bulk_set_metadata("Test-category", entries)

    a = await dir_svc.get_metadata("Test-category", "Test-category/Test-resource/a")
    b = await dir_svc.get_metadata("Test-category", "Test-category/Test-resource/b")
    assert a == (10.0, 1.0)
    assert b == (20.0, 2.0)


async def test_bulk_set_empty_is_noop(dir_svc, init_db):
    await dir_svc.bulk_set_metadata("Test-category", {})


# -----------------------------------------------------------------------
# ----------------------- calculate_directory_metadata --------------------
# -----------------------------------------------------------------------

async def test_calculate_recursive(
    dir_svc, init_db, local_resource_handler_service, local_resource_dir: Path
):
    """Recursive calculation should sum all video files in the tree.

    Tree:
        movie_a.mp4 (100) + movie_b.mp4 (200) + subdir/movie_c.mp4 (300) = 600
        notes.txt is not a video → excluded.
        subdir/empty/ is a dir with no videos → 0 contribution.
    """
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    total, mtime = await dir_svc.calculate_directory_metadata(
        abs_path, skipCache=True, recursiveCalculation=True,
    )
    assert total == 600.0
    assert mtime > 0


async def test_calculate_non_recursive_uses_cached_subdirs(
    dir_svc, init_db, local_resource_handler_service, local_resource_dir: Path
):
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    # Pre-seed subdir metadata in DB.
    subdir_db_path = handler.convert_to_DB_format_path(
        str(local_resource_dir / "subdir").replace("\\", "/")
    )
    await dir_svc.set_metadata("Test-category", subdir_db_path, 300.0, 1.0)

    total, mtime = await dir_svc.calculate_directory_metadata(
        abs_path, skipCache=True, recursiveCalculation=False,
    )
    # Non-recursive fetches subdir metadata from cache/DB: 300 + own files (100+200)=600
    assert total == 600.0


async def test_calculate_serves_from_cache_when_available(
    dir_svc, init_db, local_resource_handler_service, local_resource_dir, local_cache_service,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    root_fs = str(local_resource_dir).replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=root_fs, category="Test-category", handler=handler,
    )

    db_path = handler.convert_to_DB_format_path(root_fs)
    local_cache_service.set(f"Test-category:{db_path}", (777.0, 888.0))

    total, mtime = await dir_svc.calculate_directory_metadata(
        abs_path, skipCache=False, recursiveCalculation=True,
    )
    assert (total, mtime) == (777.0, 888.0)


async def test_calculate_returns_zeros_for_null_category(dir_svc, init_db):
    abs_path = AbsolutePath(abs_path=None, category=None, handler=None)
    total, mtime = await dir_svc.calculate_directory_metadata(abs_path)
    assert (total, mtime) == (0.0, 0.0)


async def test_get_metadata_db_hit_not_in_cache(
    dir_svc, init_db, local_cache_service,
):
    await dir_svc.set_metadata("Test-category", "db-only/path", 42.0, 99.0)
    local_cache_service.delete("Test-category:db-only/path")

    result = await dir_svc.get_metadata("Test-category", "db-only/path")
    assert result == (42.0, 99.0)
    assert local_cache_service.get("Test-category:db-only/path") == (42.0, 99.0)


async def test_calculate_error_returns_negative_ones(
    dir_svc, init_db, local_resource_handler_service,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    abs_path = AbsolutePath.from_existing_path(
        path="Z:/nonexistent/directory",
        category="Test-category",
        handler=handler,
    )
    total, mtime = await dir_svc.calculate_directory_metadata(
        abs_path, skipCache=True, recursiveCalculation=True,
    )
    assert total == -1.0
    assert mtime == -1.0


# -----------------------------------------------------------------------
# ----------------------- batch_update_metadata_forward -------------------
# -----------------------------------------------------------------------

async def test_batch_update_metadata_forward_empty_is_noop(dir_svc, init_db):
    await dir_svc.batch_update_metadata_forward("Test-category", [])


async def test_batch_update_metadata_forward_traverses_parents(
    dir_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    subdir_db = handler.convert_to_DB_format_path(
        str(local_resource_dir / "subdir").replace("\\", "/")
    )

    await dir_svc.batch_update_metadata_forward("Test-category", [subdir_db])

    result = await dir_svc.get_metadata("Test-category", subdir_db)
    assert result is not None
    assert result[0] == 300.0


# -----------------------------------------------------------------------
# ----------------------- update_directory_metadata_forward ---------------
# -----------------------------------------------------------------------

async def test_update_forward_persists_root(
    dir_svc, init_db, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    subdir_fs = str(local_resource_dir / "subdir").replace("\\", "/")
    abs_path = AbsolutePath.from_existing_path(
        path=subdir_fs, category="Test-category", handler=handler,
    )

    await dir_svc.update_directory_metadata_forward(abs_path)

    # The subdir metadata should now be persisted (300 bytes from movie_c.mp4).
    subdir_db_path = handler.convert_to_DB_format_path(subdir_fs)
    result = await dir_svc.get_metadata("Test-category", subdir_db_path)
    assert result is not None
    assert result[0] == 300.0


async def test_update_forward_stops_on_error(
    dir_svc, init_db, local_resource_handler_service,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    abs_path = AbsolutePath.from_existing_path(
        path="Z:/nonexistent/deep/path",
        category="Test-category",
        handler=handler,
    )
    await dir_svc.update_directory_metadata_forward(abs_path)
