"""
Behaviour specification — what a migration does to series membership.

A migrated video keeps its id, so the series it is in keeps listing it and nothing about
the series has to change. The one exception is an overwrite: the video already sitting at
the target path is deleted to make room, and a series listing it would otherwise be left
holding the id of a video that no longer exists.
"""

import pytest

from src.features.migration.migration_task import MigrationTaskModel, TaskStatus
from src.platform.storage.absolute_path import AbsolutePath
from tests.series_helpers import series_name_of, stored_series

pytestmark = pytest.mark.unit


def _abs(handler_svc, category, pseudo, sub=None):
    handler = handler_svc.get_handler(category)
    return AbsolutePath.from_existing_path(
        path=handler.resolve_path(category, pseudo, sub),
        category=category,
        handler=handler,
    )


def _db_path(handler_svc, category, fs_path) -> str:
    handler = handler_svc.get_handler(category)
    return handler.convert_to_DB_format_path(str(fs_path).replace("\\", "/"))


async def _migrate(svc, source, target, strategy="skip"):
    task = await svc.create_task(source, target, conflict_strategy=strategy)
    [_ async for _ in svc.run_task(str(task.id))]
    return await MigrationTaskModel.get(task.id)


async def test_a_migrated_video_keeps_its_place_in_its_series(
    two_cat_migration_svc, two_cat_handler_service, video_factory, series_factory,
    local_resource_dir, target_dir,
):
    hs = two_cat_handler_service
    # Given series "Show" stored as [a, moving, b]
    # And "moving" is a file in the source category
    moving = await video_factory(
        name="moving",
        path=_db_path(hs, "Test-category", local_resource_dir / "movie_a.mp4"),
    )
    a = await video_factory(name="a")
    b = await video_factory(name="b")
    await series_factory("Show", a, moving, b)

    # When "moving" is migrated to the target category
    task = await _migrate(
        two_cat_migration_svc,
        _abs(hs, "Test-category", "Test-resource", "/movie_a.mp4"),
        _abs(hs, "Target-category", "Target-resource", None),
    )
    assert task.status == TaskStatus.COMPLETED

    # Then "Show" is still stored as [a, moving, b]
    assert await stored_series("Show") == ["a", "moving", "b"]
    # And "moving" still references "Show" by seriesId
    assert await series_name_of(moving) == "Show"


async def test_an_overwrite_removes_the_replaced_video_from_its_series(
    two_cat_migration_svc, two_cat_handler_service, video_factory, series_factory,
    local_resource_dir, target_dir,
):
    hs = two_cat_handler_service
    # Given series "Old" stored as [kept, replaced]
    # And "replaced" is a file at the target path
    (target_dir / "movie_b.mp4").write_bytes(b"old")
    replaced = await video_factory(
        name="replaced",
        path=_db_path(hs, "Target-category", target_dir / "movie_b.mp4"),
        category="Target-category",
    )
    kept = await video_factory(name="kept")
    await series_factory("Old", kept, replaced)
    # And "incoming" is a file in the source category with the same file name
    await video_factory(
        name="incoming",
        path=_db_path(hs, "Test-category", local_resource_dir / "movie_b.mp4"),
    )

    # When "incoming" is migrated to the target with the overwrite strategy
    task = await _migrate(
        two_cat_migration_svc,
        _abs(hs, "Test-category", "Test-resource", "/movie_b.mp4"),
        _abs(hs, "Target-category", "Target-resource", None),
        strategy="overwrite",
    )
    assert task.status == TaskStatus.COMPLETED

    # Then "Old" is stored as [kept]
    assert await stored_series("Old") == ["kept"]
