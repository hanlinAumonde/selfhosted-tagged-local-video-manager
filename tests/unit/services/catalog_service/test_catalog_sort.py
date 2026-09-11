"""
Behaviour specification — the ``LastUpdate`` sort option.

The catalogue already ordered by ``lastModifyTime`` as its unnamed fallback for any
unrecognised sort value. Making it a first-class option means a caller can ask for
"newest on disk" explicitly, and ``Latest`` is free to mean only "most recently
viewed" — the two orders differ whenever a file was added long after it was watched.
"""

import pytest

from src.features.catalog.catalog_service import VideoSearchCriteria, VideoSortOption

pytestmark = pytest.mark.unit


class _NoLocks:
    """A lock registry that never reports a lock; sorting does not depend on lock state."""

    async def locked_paths(self, db_paths) -> set[str]:
        return set()

    async def is_locked(self, db_path: str) -> bool:
        return False


def _criteria(**kwargs) -> VideoSearchCriteria:
    return VideoSearchCriteria(page_number=1, page_size=10, **kwargs)


# -----------------------------------------------------------------------
# ---------------------- Ordering by file mtime --------------------------
# -----------------------------------------------------------------------

async def test_last_update_sort_orders_by_last_modify_time_descending(
    catalog_svc_factory, init_db, video_factory,
):
    await video_factory(name="oldest_on_disk", lastModifyTime=100.0, lastViewTime=300.0)
    await video_factory(name="newest_on_disk", lastModifyTime=300.0, lastViewTime=100.0)
    await video_factory(name="middle_on_disk", lastModifyTime=200.0, lastViewTime=200.0)
    svc = catalog_svc_factory(_NoLocks())

    page = await svc.search_videos(_criteria(sort_by=VideoSortOption.LastUpdate.value))

    assert [v.name for v in page.videos] == [
        "newest_on_disk", "middle_on_disk", "oldest_on_disk",
    ]


async def test_last_update_sort_differs_from_latest_sort(
    catalog_svc_factory, init_db, video_factory,
):
    await video_factory(name="added_late", lastModifyTime=300.0, lastViewTime=100.0)
    await video_factory(name="watched_late", lastModifyTime=100.0, lastViewTime=300.0)
    svc = catalog_svc_factory(_NoLocks())

    by_view = await svc.search_videos(_criteria(sort_by=VideoSortOption.Latest.value))
    by_mtime = await svc.search_videos(_criteria(sort_by=VideoSortOption.LastUpdate.value))

    assert [v.name for v in by_view.videos] == ["watched_late", "added_late"]
    assert [v.name for v in by_mtime.videos] == ["added_late", "watched_late"]


# -----------------------------------------------------------------------
# ---------------------- What LastUpdate must not do ---------------------
# -----------------------------------------------------------------------

async def test_last_update_sort_does_not_filter_out_unloved_videos(
    catalog_svc_factory, init_db, video_factory,
):
    await video_factory(name="loved_one", loved=True)
    await video_factory(name="plain_one", loved=False)
    svc = catalog_svc_factory(_NoLocks())

    page = await svc.search_videos(_criteria(sort_by=VideoSortOption.LastUpdate.value))

    assert {v.name for v in page.videos} == {"loved_one", "plain_one"}
    assert page.total_count == 2
