"""
Behaviour specification — a batch update that re-orders a series.

The planner in ``SeriesService`` decides the numbers (see
``tests/unit/features/catalog/test_series_reorder_plan.py``). What is under test here is
what ``batch_update`` does with that plan: which documents it actually writes.

The distinction matters because the request names only the selected videos. Before this
change, ``batch_update`` wrote a series order to each selected video and nothing else, so
the numbers it wrote were positions within the selection — 1..n counted from the first
selected row, colliding with whatever the unselected members already carried. A selection
of b, c, d reversed inside a, b, c, d, e came out ordered correctly and numbered 1, 1, 2,
3, 5.

Writing the plan means the batch now also touches videos the caller never named: members
of the target series that were not selected, and members left behind in the series the
selection departed. It must still touch only the ones whose stored value actually changes
— a selection that permutes itself inside a healthy series has no business rewriting the
rest of the series.

Every scenario runs over a *selection* rather than a single video, and the selected videos
never start from the same series state. That is the capability under test: which rows a
mixed selection changes, which it leaves alone, and whether the numbers left in the
database are contiguous afterwards.
"""

import pytest

from src.features.browsing.batch_operation_service import BatchResultType
from src.features.catalog.video import VideoModel
from src.schema.types.pydantic_types.batch_operation_type import (
    SeriesOperationInputModel,
    SeriesOrderEntryInputModel,
    TagsOperationMappingInputModel,
)

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


def _writes(events) -> int:
    """How many documents the batch wrote, as its own outcome reports it."""
    message = _outcome(events).message or ""
    return int(message.split(" out of ")[1].split()[0])


async def _read(*videos) -> list[tuple]:
    """Each video's stored series membership, re-read from the database."""
    refreshed = [await VideoModel.get(v.id) for v in videos]
    return [(v.seriesName, v.seriesOrder) for v in refreshed]


async def _series_reads(name: str) -> list[str]:
    """The stored series, as video names in ascending order."""
    members = await VideoModel.find({"seriesName": name}).to_list()
    return [m.name for m in sorted(members, key=lambda m: m.seriesOrder)]


async def _series_orders(name: str) -> list[int]:
    members = await VideoModel.find({"seriesName": name}).to_list()
    return sorted(m.seriesOrder for m in members)


# -----------------------------------------------------------------------
# ---------------- re-ordering inside one existing series ----------------
# -----------------------------------------------------------------------

async def test_reversing_a_middle_subset_stores_contiguous_orders_for_the_whole_series(
    init_db, video_factory, batch_svc
):
    await video_factory(name="a", seriesName="Show", seriesOrder=1)
    b = await video_factory(name="b", seriesName="Show", seriesOrder=2)
    c = await video_factory(name="c", seriesName="Show", seriesOrder=3)
    d = await video_factory(name="d", seriesName="Show", seriesOrder=4)
    await video_factory(name="e", seriesName="Show", seriesOrder=5)

    await _run(batch_svc, [b, c, d], _series_op("Show", d, c, b))

    assert await _series_reads("Show") == ["a", "d", "c", "b", "e"]
    assert await _series_orders("Show") == [1, 2, 3, 4, 5]


async def test_unselected_members_are_written_when_their_number_has_to_change(
    init_db, video_factory, batch_svc
):
    a = await video_factory(name="a", seriesName="Show", seriesOrder=1)
    b = await video_factory(name="b", seriesName="Show", seriesOrder=1)
    c = await video_factory(name="c", seriesName="Show", seriesOrder=2)
    tail = await video_factory(name="tail", seriesName="Show", seriesOrder=5)

    events = await _run(batch_svc, [a, b, c], _series_op("Show", c, b, a))

    # tail never moved, but it was the fourth of four while carrying a 5.
    assert (await _read(tail))[0] == ("Show", 4)
    assert await _series_orders("Show") == [1, 2, 3, 4]
    assert _outcome(events).result_type is BatchResultType.Success


async def test_unselected_members_that_need_no_change_are_not_written(
    init_db, video_factory, batch_svc
):
    a = await video_factory(name="a", seriesName="Show", seriesOrder=1)
    b = await video_factory(name="b", seriesName="Show", seriesOrder=2)
    c = await video_factory(name="c", seriesName="Show", seriesOrder=3)
    d = await video_factory(name="d", seriesName="Show", seriesOrder=4)
    e = await video_factory(name="e", seriesName="Show", seriesOrder=5)

    events = await _run(batch_svc, [b, c, d], _series_op("Show", d, c, b))

    # Only b and d move: c keeps the middle slot, and a and e were never in play.
    assert await _read(a, c, e) == [("Show", 1), ("Show", 3), ("Show", 5)]
    assert _writes(events) == 2


async def test_a_selection_already_in_the_requested_order_reports_nothing_to_do(
    init_db, video_factory, batch_svc
):
    a = await video_factory(name="a", seriesName="Show", seriesOrder=1)
    b = await video_factory(name="b", seriesName="Show", seriesOrder=2)
    c = await video_factory(name="c", seriesName="Show", seriesOrder=3)

    events = await _run(batch_svc, [a, b, c], _series_op("Show", a, b, c))

    assert await _read(a, b, c) == [("Show", 1), ("Show", 2), ("Show", 3)]
    assert _outcome(events).result_type is BatchResultType.AlreadyUpToDate


# -----------------------------------------------------------------------
# ------- a mixed selection: members, migrants and unassigned videos -----
# -----------------------------------------------------------------------

async def test_a_mixed_selection_lands_in_the_target_without_colliding_with_its_members(
    init_db, video_factory, batch_svc
):
    await video_factory(name="a", seriesName="Show", seriesOrder=1)
    b = await video_factory(name="b", seriesName="Show", seriesOrder=2)
    await video_factory(name="c", seriesName="Show", seriesOrder=3)
    x = await video_factory(name="x", seriesName="Other", seriesOrder=1)
    await video_factory(name="y", seriesName="Other", seriesOrder=2)
    n = await video_factory(name="n")

    await _run(batch_svc, [b, x, n], _series_op("Show", b, x, n))

    assert await _read(b, x, n) == [("Show", 2), ("Show", 4), ("Show", 5)]
    assert await _series_orders("Show") == [1, 2, 3, 4, 5]


async def test_the_series_a_selection_departed_is_compacted_in_the_same_batch(
    init_db, video_factory, batch_svc
):
    v1 = await video_factory(name="v1", seriesName="Other", seriesOrder=1)
    v2 = await video_factory(name="v2", seriesName="Other", seriesOrder=2)
    v3 = await video_factory(name="v3", seriesName="Other", seriesOrder=3)
    v4 = await video_factory(name="v4", seriesName="Other", seriesOrder=4)
    v5 = await video_factory(name="v5", seriesName="Other", seriesOrder=5)

    await _run(batch_svc, [v2, v4], _series_op("Show", v2, v4))

    assert await _read(v1, v3, v5) == [("Other", 1), ("Other", 2), ("Other", 3)]


async def test_a_selection_spanning_two_donor_series_compacts_both(
    init_db, video_factory, batch_svc
):
    a1 = await video_factory(name="a1", seriesName="A", seriesOrder=1)
    a2 = await video_factory(name="a2", seriesName="A", seriesOrder=2)
    a3 = await video_factory(name="a3", seriesName="A", seriesOrder=3)
    b1 = await video_factory(name="b1", seriesName="B", seriesOrder=1)
    b2 = await video_factory(name="b2", seriesName="B", seriesOrder=2)
    b3 = await video_factory(name="b3", seriesName="B", seriesOrder=3)

    await _run(batch_svc, [a2, b1], _series_op("Show", a2, b1))

    assert await _read(a1, a3) == [("A", 1), ("A", 2)]
    assert await _read(b2, b3) == [("B", 1), ("B", 2)]


async def test_videos_outside_the_selection_and_outside_the_series_are_never_written(
    init_db, video_factory, batch_svc
):
    await video_factory(name="s1", seriesName="Show", seriesOrder=1)
    x = await video_factory(name="x", seriesName="Other", seriesOrder=1)
    await video_factory(name="y", seriesName="Other", seriesOrder=2)
    bystander = await video_factory(name="z", seriesName="Untouched", seriesOrder=7)

    await _run(batch_svc, [x], _series_op("Show", x))

    assert (await _read(bystander))[0] == ("Untouched", 7)


# -----------------------------------------------------------------------
# ---------------------------- clearing ----------------------------------
# -----------------------------------------------------------------------

async def test_clearing_a_selection_leaves_the_rest_of_the_series_contiguous(
    init_db, video_factory, batch_svc
):
    a = await video_factory(name="a", seriesName="Show", seriesOrder=1)
    b = await video_factory(name="b", seriesName="Show", seriesOrder=2)
    c = await video_factory(name="c", seriesName="Show", seriesOrder=3)
    d = await video_factory(name="d", seriesName="Show", seriesOrder=4)

    await _run(batch_svc, [b, d], _series_op(None, clear=True))

    assert await _read(b, d) == [(None, None), (None, None)]
    assert await _read(a, c) == [("Show", 1), ("Show", 2)]


async def test_clearing_a_selection_that_spans_series_compacts_each_of_them(
    init_db, video_factory, batch_svc
):
    a1 = await video_factory(name="a1", seriesName="A", seriesOrder=1)
    a2 = await video_factory(name="a2", seriesName="A", seriesOrder=2)
    a3 = await video_factory(name="a3", seriesName="A", seriesOrder=3)
    b1 = await video_factory(name="b1", seriesName="B", seriesOrder=1)
    b2 = await video_factory(name="b2", seriesName="B", seriesOrder=2)

    await _run(batch_svc, [a1, b2], _series_op(None, clear=True))

    assert await _read(a2, a3) == [("A", 1), ("A", 2)]
    assert (await _read(b1))[0] == ("B", 1)


# -----------------------------------------------------------------------
# ------------------ coexistence with the other fields -------------------
# -----------------------------------------------------------------------

async def test_a_series_reorder_carries_the_tag_and_author_edits_in_the_same_pass(
    init_db, video_factory, batch_svc
):
    a = await video_factory(
        name="a", seriesName="Show", seriesOrder=1, author="one", tags=["keep"]
    )
    b = await video_factory(name="b", seriesName="Other", seriesOrder=1, author="two")
    c = await video_factory(name="c", author="three", tags=["keep"])

    events = await _run(
        batch_svc,
        [a, b, c],
        _series_op("Show", c, b, a),
        author="unified",
        tagsOperation=TagsOperationMappingInputModel(addTags=["4k"], removeTags=[]),
    )

    refreshed = [await VideoModel.get(v.id) for v in (a, b, c)]
    assert all(v.author == "unified" for v in refreshed)
    assert all("4k" in v.tags for v in refreshed)
    assert await _series_orders("Show") == [1, 2, 3]
    assert _outcome(events).result_type is BatchResultType.Success
