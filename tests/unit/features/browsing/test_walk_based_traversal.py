"""
Behaviour specification — recursive metadata calculation is built on ``handler.walk``.

Recursion used to be written per caller, each listing directory by directory on the
event loop. ``_calculate_directory_metadata_impl`` was ``async def`` without a single
await that could suspend: a Refresh Metadata on a big tree was one unbroken block of the
loop. It now consumes ``walk``.

What it reports must not change — the totals are already pinned in
``test_dir_metadata_service.py``. What is pinned here is what a flat walk could easily
lose: the per-directory records written along the way.

Fixture tree (``local_resource_dir``), video extension ``.mp4``:
    movie_a.mp4 (100 B), movie_b.mp4 (200 B), notes.txt, subdir/movie_c.mp4 (300 B),
    subdir/empty/
"""

import asyncio
import os
from pathlib import Path

import pytest

from src.platform.storage.absolute_path import AbsolutePath

pytestmark = pytest.mark.unit

CATEGORY = "Test-category"


def _abs(handler, path: Path) -> AbsolutePath:
    return AbsolutePath.from_existing_path(
        path=str(path).replace("\\", "/"), category=CATEGORY, handler=handler,
    )


def _db_path(handler, path: Path) -> str:
    return handler.convert_to_DB_format_path(str(path).replace("\\", "/"))


# Scenario: every sub-directory on the way gets its own aggregate stored
#   Given the fixture tree
#   When calculate_directory_metadata is awaited on the root with recursion and no cache
#   Then the stored metadata for subdir is (300, mtime of movie_c.mp4) — reading it
#       later does not recompute
async def test_recursive_calculation_stores_each_sub_directory_aggregate(
    dir_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    handler = local_resource_handler_service.get_handler(CATEGORY)
    movie_c_mtime = os.stat(local_resource_dir / "subdir" / "movie_c.mp4").st_mtime

    await dir_svc.calculate_directory_metadata(
        _abs(handler, local_resource_dir), skipCache=True, recursiveCalculation=True,
    )

    stored = await dir_svc.get_metadata(CATEGORY, _db_path(handler, local_resource_dir / "subdir"))
    assert stored == (300.0, movie_c_mtime)


# Scenario: a sub-directory emptied outside the app has its stale record overwritten
#   Given subdir/empty stored as (500, 1700000000) from a time it held a video
#   And it holds nothing at all now
#   When calculate_directory_metadata is awaited on the root with recursion and no cache
#   Then the stored metadata for subdir/empty is (0, 0) — otherwise the folder comes back
#       in the browser with a size it no longer has
async def test_recursive_calculation_overwrites_a_stale_record_of_an_emptied_directory(
    dir_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    handler = local_resource_handler_service.get_handler(CATEGORY)
    emptied = _db_path(handler, local_resource_dir / "subdir" / "empty")
    await dir_svc.set_metadata(CATEGORY, emptied, 500.0, 1700000000.0)

    await dir_svc.calculate_directory_metadata(
        _abs(handler, local_resource_dir), skipCache=True, recursiveCalculation=True,
    )

    assert await dir_svc.get_metadata(CATEGORY, emptied) == (0.0, 0.0)


# Scenario: the calculation actually yields the event loop while it traverses
#   Given the fixture tree
#   And a concurrent task that only records that it got to run
#   When calculate_directory_metadata is awaited on the root with recursion and no cache
#   Then the concurrent task had run by the time the traversal received its last batch —
#       a traversal that never suspends would hold it off until the database write
async def test_recursive_calculation_lets_other_tasks_run_during_the_traversal(
    dir_svc, init_db, local_resource_handler_service, local_resource_dir: Path, monkeypatch,
):
    handler = local_resource_handler_service.get_handler(CATEGORY)
    other_task_ran = asyncio.Event()
    seen_while_traversing: list[bool] = []

    real_walk = handler.walk

    async def observed_walk(path: str):
        async for batch in real_walk(path):
            seen_while_traversing.append(other_task_ran.is_set())
            yield batch

    monkeypatch.setattr(handler, "walk", observed_walk)

    async def other_task():
        other_task_ran.set()

    concurrent = asyncio.create_task(other_task())
    await dir_svc.calculate_directory_metadata(
        _abs(handler, local_resource_dir), skipCache=True, recursiveCalculation=True,
    )
    await concurrent

    assert seen_while_traversing, "the calculation did not traverse through walk"
    assert seen_while_traversing[-1] is True
