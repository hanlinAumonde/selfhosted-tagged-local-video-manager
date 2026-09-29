"""
Behaviour specification — planning a series re-ordering from a partial selection.

A batch edit panel only ever shows the videos the user selected, so the ordering it
sends back is a *relative* sequence over a subset. The absolute position of each video
inside the whole series is not something the panel can know: the series may hold
members that were never selected, and their numbers have to stay consistent with the
new arrangement.

So the panel states the relative order and this planner states the numbers.

One rule places the selection, with no special case for how the selection is made up:

    the slots the selection takes are the ones it already held in the target series,
    plus one appended slot per video joining the series; sorted, they are filled by the
    requested sequence in order.

A selection made entirely of existing members therefore only permutes itself and leaves
every other member exactly where it was. A selection made entirely of newcomers lands
after the existing members. A mixed selection gets both, and the order the user composed
in the panel survives intact — including a newcomer dropped between two members, which
is how the single-video panel places the video being edited.

Two further things follow from "the numbers must be right", and neither is visible in
the panel:

- the whole target series is renumbered 1..n unconditionally, so a series whose numbering
  has already drifted (duplicates, gaps) comes back contiguous after one save;
- every series the selection *left* is compacted too. Moving three videos out of a series
  of eight otherwise leaves five members carrying the orders 1, 4, 5, 7, 8.
"""

import pytest
import pytest_asyncio

from src.features.catalog.series_service import SeriesService

pytestmark = pytest.mark.unit


class _World:
    """The videos a scenario set up, so a plan can be read back as names.

    A plan names videos by id, which no assertion can be written against. Keeping the
    id-to-name map here rather than on the planned placement keeps the production type
    down to what the caller actually writes: an id, a series name, an order.
    """

    def __init__(self, video_factory):
        self._factory = video_factory
        self._names: dict[str, str] = {}

    async def video(self, name, series=None, order=None):
        video = await self._factory(name=name, seriesName=series, seriesOrder=order)
        self._names[str(video.id)] = name
        return video

    def names_in(self, placements, series_name) -> list[str]:
        """Names of the videos a plan puts in `series_name`, in ascending order."""
        rows = sorted(
            (p for p in placements if p.series_name == series_name),
            key=lambda p: p.order,
        )
        return [self._names[p.video_id] for p in rows]


@pytest_asyncio.fixture
def world(video_factory) -> _World:
    return _World(video_factory)


def _orders_in(placements, series_name) -> list[int]:
    return sorted(p.order for p in placements if p.series_name == series_name)


def _placement_for(placements, video):
    return next(p for p in placements if p.video_id == str(video.id))


def _ids(*videos) -> list[str]:
    return [str(v.id) for v in videos]


# -----------------------------------------------------------------------
# --------------- reordering a subset of an existing series --------------
# -----------------------------------------------------------------------

async def test_reordering_a_middle_subset_leaves_the_outside_members_in_place(
    init_db, world
):
    await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    c = await world.video("c", "Show", 3)
    d = await world.video("d", "Show", 4)
    await world.video("e", "Show", 5)

    plan = await SeriesService().plan_assignment("Show", _ids(d, c, b))

    assert world.names_in(plan, "Show") == ["a", "d", "c", "b", "e"]


async def test_a_reordered_subset_is_numbered_contiguously_across_the_whole_series(
    init_db, world
):
    await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    c = await world.video("c", "Show", 3)
    d = await world.video("d", "Show", 4)
    await world.video("e", "Show", 5)

    plan = await SeriesService().plan_assignment("Show", _ids(d, c, b))

    assert _orders_in(plan, "Show") == [1, 2, 3, 4, 5]


async def test_selected_videos_only_take_the_slots_they_already_occupied(
    init_db, world
):
    a = await world.video("a", "Show", 1)
    await world.video("b", "Show", 2)
    c = await world.video("c", "Show", 3)
    await world.video("d", "Show", 4)
    e = await world.video("e", "Show", 5)

    plan = await SeriesService().plan_assignment("Show", _ids(e, c, a))

    assert world.names_in(plan, "Show") == ["e", "b", "c", "d", "a"]


async def test_a_selection_covering_the_entire_series_is_renumbered_to_the_requested_order(
    init_db, world
):
    a = await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    c = await world.video("c", "Show", 3)

    plan = await SeriesService().plan_assignment("Show", _ids(c, a, b))

    assert world.names_in(plan, "Show") == ["c", "a", "b"]
    assert _orders_in(plan, "Show") == [1, 2, 3]


# -----------------------------------------------------------------------
# ------------------- healing a series that drifted ----------------------
# -----------------------------------------------------------------------

async def test_a_series_with_duplicate_order_numbers_is_renumbered_contiguously(
    init_db, world
):
    first = await world.video("a", "Show", 1)
    await world.video("b", "Show", 1)
    second = await world.video("c", "Show", 2)
    third = await world.video("d", "Show", 3)
    await world.video("e", "Show", 5)

    plan = await SeriesService().plan_assignment("Show", _ids(third, second, first))

    orders = _orders_in(plan, "Show")
    assert orders == [1, 2, 3, 4, 5]
    assert len(set(orders)) == len(orders)


async def test_a_member_that_did_not_move_still_gets_a_corrected_number(
    init_db, world
):
    a = await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    c = await world.video("c", "Show", 3)
    tail = await world.video("tail", "Show", 5)

    plan = await SeriesService().plan_assignment("Show", _ids(a, b, c))

    assert world.names_in(plan, "Show")[-1] == "tail"
    assert _placement_for(plan, tail).order == 4


async def test_a_member_with_no_order_at_all_is_placed_after_the_numbered_ones(
    init_db, world
):
    a = await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    loose = await world.video("loose", "Show", None)

    plan = await SeriesService().plan_assignment("Show", _ids(b, a))

    assert world.names_in(plan, "Show") == ["b", "a", "loose"]
    assert _placement_for(plan, loose).order == 3


# -----------------------------------------------------------------------
# ------------------ selections that are not yet members -----------------
# -----------------------------------------------------------------------

async def test_videos_joining_the_series_are_appended_after_the_existing_members(
    init_db, world
):
    a = await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    n1 = await world.video("n1")
    n2 = await world.video("n2")

    plan = await SeriesService().plan_assignment("Show", _ids(n1, n2))

    assert _placement_for(plan, a).order == 1
    assert _placement_for(plan, b).order == 2
    assert _placement_for(plan, n1).order == 3
    assert _placement_for(plan, n2).order == 4


async def test_placing_a_selection_into_a_name_no_video_uses_yet_numbers_it_from_one(
    init_db, world
):
    v1 = await world.video("v1")
    v2 = await world.video("v2")
    v3 = await world.video("v3")

    plan = await SeriesService().plan_assignment("Brand New", _ids(v2, v3, v1))

    assert world.names_in(plan, "Brand New") == ["v2", "v3", "v1"]
    assert _orders_in(plan, "Brand New") == [1, 2, 3]


async def test_a_selected_id_that_no_longer_exists_is_left_out_of_the_plan(
    init_db, world
):
    a = await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    vanished = "507f1f77bcf86cd799439011"

    plan = await SeriesService().plan_assignment("Show", [vanished, str(a.id)])

    assert {p.video_id for p in plan} == {str(a.id), str(b.id)}
    assert _orders_in(plan, "Show") == [1, 2]


async def test_a_selected_id_that_is_not_an_object_id_is_left_out_of_the_plan(
    init_db, world
):
    a = await world.video("a", "Show", 1)
    await world.video("b", "Show", 2)

    plan = await SeriesService().plan_assignment("Show", ["not-an-id", str(a.id)])

    assert world.names_in(plan, "Show") == ["a", "b"]
    assert _orders_in(plan, "Show") == [1, 2]


# -----------------------------------------------------------------------
# ------- a mixed selection: members, migrants and unassigned videos -----
# -----------------------------------------------------------------------
#
# The selection spans three kinds of video at once — some already in the target
# series, some in other series that also hold videos nobody selected, and some in
# no series at all. Every claim below has to hold whatever order the panel asks for,
# which is why the same starting arrangement is replayed under different orderings.

async def test_a_mixed_selection_fills_its_own_slots_then_appends_the_newcomers(
    init_db, world
):
    await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    c = await world.video("c", "Show", 3)
    x = await world.video("x", "Other", 1)
    await world.video("y", "Other", 2)
    n = await world.video("n")

    plan = await SeriesService().plan_assignment("Show", _ids(c, b, x, n))

    assert world.names_in(plan, "Show") == ["a", "c", "b", "x", "n"]
    assert _orders_in(plan, "Show") == [1, 2, 3, 4, 5]


async def test_the_requested_sequence_survives_when_newcomers_sit_between_members(
    init_db, world
):
    await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    c = await world.video("c", "Show", 3)
    n = await world.video("n")

    plan = await SeriesService().plan_assignment("Show", _ids(c, n, b))

    assert world.names_in(plan, "Show") == ["a", "c", "n", "b"]
    assert _orders_in(plan, "Show") == [1, 2, 3, 4]


async def test_a_series_the_selection_left_is_compacted(init_db, world):
    await world.video("v1", "Other", 1)
    v2 = await world.video("v2", "Other", 2)
    await world.video("v3", "Other", 3)
    v4 = await world.video("v4", "Other", 4)
    await world.video("v5", "Other", 5)

    plan = await SeriesService().plan_assignment("Show", _ids(v2, v4))

    assert world.names_in(plan, "Other") == ["v1", "v3", "v5"]
    assert _orders_in(plan, "Other") == [1, 2, 3]


async def test_every_donor_series_is_compacted_when_the_selection_spans_several(
    init_db, world
):
    await world.video("a1", "A", 1)
    a2 = await world.video("a2", "A", 2)
    await world.video("a3", "A", 3)
    b1 = await world.video("b1", "B", 1)
    await world.video("b2", "B", 2)
    await world.video("b3", "B", 3)

    plan = await SeriesService().plan_assignment("Show", _ids(a2, b1))

    assert world.names_in(plan, "A") == ["a1", "a3"]
    assert _orders_in(plan, "A") == [1, 2]
    assert world.names_in(plan, "B") == ["b2", "b3"]
    assert _orders_in(plan, "B") == [1, 2]


async def test_videos_left_untouched_in_a_donor_series_keep_their_series_name(
    init_db, world
):
    await world.video("v1", "Other", 1)
    v2 = await world.video("v2", "Other", 2)
    await world.video("v3", "Other", 3)

    plan = await SeriesService().plan_assignment("Show", _ids(v2))

    assert world.names_in(plan, "Other") == ["v1", "v3"]
    assert world.names_in(plan, "Show") == ["v2"]


async def test_a_donor_series_emptied_by_the_selection_produces_no_leftover_plan(
    init_db, world
):
    x = await world.video("x", "Other", 1)
    y = await world.video("y", "Other", 2)

    plan = await SeriesService().plan_assignment("Show", _ids(x, y))

    assert world.names_in(plan, "Other") == []
    assert world.names_in(plan, "Show") == ["x", "y"]


async def test_the_target_series_is_not_treated_as_a_donor_of_itself(init_db, world):
    a = await world.video("a", "Show", 1)
    await world.video("b", "Show", 2)
    c = await world.video("c", "Show", 3)

    plan = await SeriesService().plan_assignment("Show", _ids(c, a))

    ids = [p.video_id for p in plan]
    assert len(ids) == len(set(ids))
    assert _orders_in(plan, "Show") == [1, 2, 3]


async def test_reversing_a_mixed_selection_reverses_only_its_own_slots(
    init_db, world
):
    await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    await world.video("c", "Show", 3)
    d = await world.video("d", "Show", 4)
    x = await world.video("x", "Other", 1)
    y = await world.video("y", "Other", 2)

    plan = await SeriesService().plan_assignment("Show", _ids(d, b, x))

    assert world.names_in(plan, "Show") == ["a", "d", "c", "b", "x"]
    assert world.names_in(plan, "Other") == ["y"]
    assert _placement_for(plan, y).order == 1


# -----------------------------------------------------------------------
# ----------------------- clearing a selection ---------------------------
# -----------------------------------------------------------------------

async def test_clearing_a_selection_compacts_the_series_it_emptied_out_of(
    init_db, world
):
    await world.video("a", "Show", 1)
    b = await world.video("b", "Show", 2)
    await world.video("c", "Show", 3)
    d = await world.video("d", "Show", 4)

    plan = await SeriesService().plan_clear(_ids(b, d))

    assert _placement_for(plan, b).series_name is None
    assert _placement_for(plan, b).order is None
    assert _placement_for(plan, d).series_name is None
    assert world.names_in(plan, "Show") == ["a", "c"]
    assert _orders_in(plan, "Show") == [1, 2]


async def test_clearing_a_selection_that_spans_series_compacts_each_of_them(
    init_db, world
):
    a1 = await world.video("a1", "A", 1)
    await world.video("a2", "A", 2)
    await world.video("a3", "A", 3)
    await world.video("b1", "B", 1)
    b2 = await world.video("b2", "B", 2)

    plan = await SeriesService().plan_clear(_ids(a1, b2))

    assert world.names_in(plan, "A") == ["a2", "a3"]
    assert _orders_in(plan, "A") == [1, 2]
    assert world.names_in(plan, "B") == ["b1"]
    assert _orders_in(plan, "B") == [1]
