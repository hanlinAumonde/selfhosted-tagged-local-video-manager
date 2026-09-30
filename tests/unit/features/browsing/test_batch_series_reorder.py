"""
Behaviour specification — a batch update or delete that touches series membership.

Where each video lands is decided by ``SeriesService`` (see
``tests/unit/features/catalog/test_series_assignment.py``). What is under test here is
that ``batch_update`` routes the selection there, and that its outcome report counts the
series change. The order now lives on the series document rather than on each video, so
a selection that only reorders itself inside a series writes no video document at all —
yet something did change, and the report must not claim the batch was a no-op.

Deleting videos in a batch has to take them out of their series too, whether the batch
names videos by id or walks a directory.

Every scenario runs over a *selection* rather than a single video, and the selected videos
never start from the same series state.
"""

from pathlib import Path

import pytest

from src.features.browsing.batch_operation_service import BatchResultType
from src.features.catalog.video import VideoModel
from src.platform.storage.absolute_path import AbsolutePath
from src.schema.types.pydantic_types.batch_operation_type import (
    SeriesOperationInputModel,
    SeriesOrderEntryInputModel,
    TagsOperationMappingInputModel,
)
from tests.series_helpers import series_name_of, stored_series

pytestmark = pytest.mark.unit

CATEGORY = "Test-category"


def _series_op(name, *videos, clear: bool = False) -> SeriesOperationInputModel:
    """A series operation carrying the selection in the requested relative order."""
    return SeriesOperationInputModel(
        name=name,
        clear=clear,
        orders=[
            SeriesOrderEntryInputModel(videoId=str(v.id), order=i)
            for i, v in enumerate(videos, start=1)
        ],
    )


async def _run(batch_svc, selection, series_op, **kwargs):
    """Run one batch update over a selection, by ID, and drain the report stream."""
    return [
        event
        async for event in batch_svc.batch_update(
            category=CATEGORY,
            videoIDs=[str(v.id) for v in selection],
            fileEntries=None,
            author=kwargs.get("author"),
            tagsOperation=kwargs.get(
                "tagsOperation",
                TagsOperationMappingInputModel(addTags=[], removeTags=[]),
            ),
            seriesOperation=series_op,
        )
    ]


def _outcome(events):
    """The settled report the stream ends on."""
    return next(e for e in events if e.result_type is not None)


async def _videos(video_factory, *names):
    return [await video_factory(name=n) for n in names]


def _abs_dir(handler_svc, directory: Path) -> AbsolutePath:
    handler = handler_svc.get_handler(CATEGORY)
    return AbsolutePath.from_existing_path(
        path=str(directory).replace("\\", "/"), category=CATEGORY, handler=handler,
    )


async def _video_on_disk(video_factory, handler_svc, directory: Path, name: str):
    """A video whose file really exists at `directory`, so a delete can remove it."""
    fs_path = directory / f"{name}.mp4"
    fs_path.write_bytes(b"x")
    handler = handler_svc.get_handler(CATEGORY)
    db_path = handler.convert_to_DB_format_path(str(fs_path).replace("\\", "/"))
    return await video_factory(name=name, path=db_path)


# -----------------------------------------------------------------------
# ---------------- re-ordering inside one existing series ----------------
# -----------------------------------------------------------------------

async def test_reversing_a_middle_subset_stores_the_whole_series_in_the_new_order(
    video_factory, series_factory, batch_svc
):
    # Given series "Show" stored as [a, b, c, d, e]
    a, b, c, d, e = await _videos(video_factory, "a", "b", "c", "d", "e")
    await series_factory("Show", a, b, c, d, e)

    # When a batch update assigns b, c, d to "Show" in the order d, c, b
    await _run(batch_svc, [b, c, d], _series_op("Show", d, c, b))

    # Then "Show" is stored as [a, d, c, b, e]
    assert await stored_series("Show") == ["a", "d", "c", "b", "e"]


async def test_a_reorder_that_writes_no_video_document_is_still_reported_as_a_success(
    video_factory, series_factory, batch_svc
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)

    # When a batch update assigns a, b, c to "Show" in the order c, b, a
    events = await _run(batch_svc, [a, b, c], _series_op("Show", c, b, a))

    # Then the batch reports Success
    assert _outcome(events).result_type is BatchResultType.Success


async def test_a_selection_already_in_the_requested_order_reports_nothing_to_do(
    video_factory, series_factory, batch_svc
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)

    # When a batch update assigns a, b, c to "Show" in the order a, b, c
    events = await _run(batch_svc, [a, b, c], _series_op("Show", a, b, c))

    # Then "Show" is still stored as [a, b, c]
    assert await stored_series("Show") == ["a", "b", "c"]
    # And the batch reports AlreadyUpToDate
    assert _outcome(events).result_type is BatchResultType.AlreadyUpToDate


# -----------------------------------------------------------------------
# ------- a mixed selection: members, migrants and unassigned videos -----
# -----------------------------------------------------------------------

async def test_a_mixed_selection_lands_in_the_target_and_leaves_its_donor(
    video_factory, series_factory, batch_svc
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)
    # And series "Other" stored as [x, y]
    x, y = await _videos(video_factory, "x", "y")
    await series_factory("Other", x, y)
    # And video n in no series
    n = await video_factory(name="n")

    # When a batch update assigns b, x, n to "Show" in that order
    await _run(batch_svc, [b, x, n], _series_op("Show", b, x, n))

    # Then "Show" is stored as [a, b, c, x, n]
    assert await stored_series("Show") == ["a", "b", "c", "x", "n"]
    # And "Other" is stored as [y]
    assert await stored_series("Other") == ["y"]
    # And x and n reference "Show" by seriesId
    assert await series_name_of(x) == "Show"
    assert await series_name_of(n) == "Show"


async def test_a_selection_spanning_two_donor_series_leaves_both(
    video_factory, series_factory, batch_svc
):
    # Given series "A" stored as [a1, a2, a3]
    a1, a2, a3 = await _videos(video_factory, "a1", "a2", "a3")
    await series_factory("A", a1, a2, a3)
    # And series "B" stored as [b1, b2, b3]
    b1, b2, b3 = await _videos(video_factory, "b1", "b2", "b3")
    await series_factory("B", b1, b2, b3)

    # When a batch update assigns a2, b1 to "Show"
    await _run(batch_svc, [a2, b1], _series_op("Show", a2, b1))

    # Then "A" is stored as [a1, a3]
    assert await stored_series("A") == ["a1", "a3"]
    # And "B" is stored as [b2, b3]
    assert await stored_series("B") == ["b2", "b3"]


# -----------------------------------------------------------------------
# ---------------------------- clearing ----------------------------------
# -----------------------------------------------------------------------

async def test_clearing_a_selection_that_spans_series_removes_it_from_each_of_them(
    video_factory, series_factory, batch_svc
):
    # Given series "A" stored as [a1, a2, a3]
    a1, a2, a3 = await _videos(video_factory, "a1", "a2", "a3")
    await series_factory("A", a1, a2, a3)
    # And series "B" stored as [b1, b2]
    b1, b2 = await _videos(video_factory, "b1", "b2")
    await series_factory("B", b1, b2)

    # When a batch update clears a1, b2
    await _run(batch_svc, [a1, b2], _series_op(None, clear=True))

    # Then "A" is stored as [a2, a3]
    assert await stored_series("A") == ["a2", "a3"]
    # And "B" is stored as [b1]
    assert await stored_series("B") == ["b1"]
    # And a1 and b2 reference no series
    assert await series_name_of(a1) is None
    assert await series_name_of(b2) is None


# -----------------------------------------------------------------------
# ------------------ coexistence with the other fields -------------------
# -----------------------------------------------------------------------

async def test_a_series_reorder_carries_the_tag_and_author_edits_in_the_same_pass(
    video_factory, series_factory, batch_svc
):
    # Given video a in series "Show" (stored as [a]), with author "one" and tag "keep"
    a = await video_factory(name="a", author="one", tags=["keep"])
    await series_factory("Show", a)
    # And video b in series "Other" (stored as [b]), with author "two"
    b = await video_factory(name="b", author="two")
    await series_factory("Other", b)
    # And video c in no series, with author "three" and tag "keep"
    c = await video_factory(name="c", author="three", tags=["keep"])

    # When a batch update sets author "unified", adds tag "4k"
    #   and assigns a, b, c to "Show" in the order c, b, a
    events = await _run(
        batch_svc,
        [a, b, c],
        _series_op("Show", c, b, a),
        author="unified",
        tagsOperation=TagsOperationMappingInputModel(addTags=["4k"], removeTags=[]),
    )

    # Then a, b and c all have author "unified" and carry tag "4k"
    refreshed = [await VideoModel.get(v.id) for v in (a, b, c)]
    assert all(v.author == "unified" for v in refreshed)
    assert all("4k" in v.tags for v in refreshed)
    # And "Show" is stored as [c, b, a]
    assert await stored_series("Show") == ["c", "b", "a"]
    # And the batch reports Success
    assert _outcome(events).result_type is BatchResultType.Success


# -----------------------------------------------------------------------
# ------------------------- deleting in a batch --------------------------
# -----------------------------------------------------------------------

async def test_a_batch_delete_by_ids_removes_the_deleted_videos_from_their_series(
    video_factory, series_factory, batch_svc, local_resource_handler_service,
    local_resource_dir: Path,
):
    # Given series "A" stored as [a1, a2, a3], whose files exist on disk
    a1, a2, a3 = [
        await _video_on_disk(video_factory, local_resource_handler_service, local_resource_dir, n)
        for n in ("a1", "a2", "a3")
    ]
    await series_factory("A", a1, a2, a3)
    # And series "B" stored as [b1, b2], whose files exist on disk
    b1, b2 = [
        await _video_on_disk(video_factory, local_resource_handler_service, local_resource_dir, n)
        for n in ("b1", "b2")
    ]
    await series_factory("B", b1, b2)

    # When a batch delete by ids removes a2 and b1
    [_ async for _ in batch_svc.batch_delete(
        dir_path=_abs_dir(local_resource_handler_service, local_resource_dir),
        videoIds=[str(a2.id), str(b1.id)],
        fileEntries=None,
    )]

    # Then "A" is stored as [a1, a3]
    assert await stored_series("A") == ["a1", "a3"]
    # And "B" is stored as [b2]
    assert await stored_series("B") == ["b2"]


async def test_a_batch_delete_by_directory_removes_the_deleted_videos_from_their_series(
    video_factory, series_factory, batch_svc, local_resource_handler_service,
    local_resource_dir: Path,
):
    # Given a directory holding a2 and b1 on disk
    doomed_dir = local_resource_dir / "doomed"
    doomed_dir.mkdir()
    a2 = await _video_on_disk(video_factory, local_resource_handler_service, doomed_dir, "a2")
    b1 = await _video_on_disk(video_factory, local_resource_handler_service, doomed_dir, "b1")
    # And series "A" stored as [a1, a2], where a1 lives outside that directory
    a1 = await _video_on_disk(video_factory, local_resource_handler_service, local_resource_dir, "a1")
    await series_factory("A", a1, a2)
    # And series "B" stored as [b1]
    await series_factory("B", b1)

    # When a batch delete removes every video in that directory
    handler = local_resource_handler_service.get_handler(CATEGORY)
    entries = [
        handler.get_entry(str(doomed_dir / f"{n}.mp4").replace("\\", "/"))
        for n in ("a2", "b1")
    ]
    [_ async for _ in batch_svc.batch_delete(
        dir_path=_abs_dir(local_resource_handler_service, doomed_dir),
        videoIds=None,
        fileEntries=entries,
    )]

    # Then "A" is stored as [a1]
    assert await stored_series("A") == ["a1"]
    # And no series named "B" exists
    assert await stored_series("B") is None
