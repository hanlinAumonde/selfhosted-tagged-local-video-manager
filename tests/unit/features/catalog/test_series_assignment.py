"""
Behaviour specification — placing videos into, and taking them out of, a series.

A series is its own document: a name and the ordered list of its members' ids. Position
is the index in that list, so there is no stored number to drift, and closing the gap a
departing video leaves is simply removing its id.

One rule places a selection, with no special case for how the selection is made up:

    the slots the selection takes are the ones it already held in the target series,
    plus one appended slot per video joining the series; sorted, they are filled by the
    requested sequence in order.

Every scenario asserts on what is stored: the target's ``videoIds`` in order, each video's
``seriesId`` back-reference, and whether a series document still exists.
"""

import pytest

from src.features.catalog.series_service import SeriesService
from src.features.catalog.video import VideoModel
from tests.series_helpers import series_name_of, stored_series

pytestmark = pytest.mark.unit

VANISHED_ID = "507f1f77bcf86cd799439011"


def _ids(*videos) -> list[str]:
    return [str(v.id) for v in videos]


async def _videos(video_factory, *names) -> list[VideoModel]:
    return [await video_factory(name=n) for n in names]


# -----------------------------------------------------------------------
# --------------- reordering a subset of an existing series --------------
# -----------------------------------------------------------------------

async def test_reordering_a_middle_subset_leaves_the_outside_members_in_place(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c, d, e]
    a, b, c, d, e = await _videos(video_factory, "a", "b", "c", "d", "e")
    await series_factory("Show", a, b, c, d, e)

    # When b, c, d are assigned to "Show" in the order d, c, b
    await SeriesService().assign("Show", _ids(d, c, b))

    # Then "Show" is stored as [a, d, c, b, e]
    assert await stored_series("Show") == ["a", "d", "c", "b", "e"]


async def test_selected_videos_only_take_the_slots_they_already_occupied(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c, d, e]
    a, b, c, d, e = await _videos(video_factory, "a", "b", "c", "d", "e")
    await series_factory("Show", a, b, c, d, e)

    # When a, c, e are assigned to "Show" in the order e, c, a
    await SeriesService().assign("Show", _ids(e, c, a))

    # Then "Show" is stored as [e, b, c, d, a]
    assert await stored_series("Show") == ["e", "b", "c", "d", "a"]


async def test_a_selection_covering_the_entire_series_is_stored_in_the_requested_order(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)

    # When a, b, c are assigned to "Show" in the order c, a, b
    await SeriesService().assign("Show", _ids(c, a, b))

    # Then "Show" is stored as [c, a, b]
    assert await stored_series("Show") == ["c", "a", "b"]


# -----------------------------------------------------------------------
# ------------------ selections that are not yet members -----------------
# -----------------------------------------------------------------------

async def test_videos_joining_the_series_are_appended_after_the_existing_members(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b]
    a, b = await _videos(video_factory, "a", "b")
    await series_factory("Show", a, b)
    # And videos n1, n2 in no series
    n1, n2 = await _videos(video_factory, "n1", "n2")

    # When n1, n2 are assigned to "Show" in that order
    await SeriesService().assign("Show", _ids(n1, n2))

    # Then "Show" is stored as [a, b, n1, n2]
    assert await stored_series("Show") == ["a", "b", "n1", "n2"]
    # And n1 and n2 both reference "Show" by seriesId
    assert await series_name_of(n1) == "Show"
    assert await series_name_of(n2) == "Show"


async def test_assigning_to_a_name_no_series_has_yet_creates_that_series(video_factory):
    # Given videos v1, v2, v3 in no series
    v1, v2, v3 = await _videos(video_factory, "v1", "v2", "v3")
    # And no series named "Brand New"
    assert await stored_series("Brand New") is None

    # When v1, v2, v3 are assigned to "Brand New" in the order v2, v3, v1
    await SeriesService().assign("Brand New", _ids(v2, v3, v1))

    # Then a series "Brand New" exists, stored as [v2, v3, v1]
    assert await stored_series("Brand New") == ["v2", "v3", "v1"]
    # And v1, v2, v3 all reference it by seriesId
    for v in (v1, v2, v3):
        assert await series_name_of(v) == "Brand New"


async def test_a_selected_id_that_no_longer_exists_is_left_out(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b]
    a, b = await _videos(video_factory, "a", "b")
    await series_factory("Show", a, b)

    # When an id with no video behind it and a are assigned to "Show", in that order
    await SeriesService().assign("Show", [VANISHED_ID, str(a.id)])

    # Then "Show" is stored as [a, b]
    assert await stored_series("Show") == ["a", "b"]


async def test_a_selected_id_that_is_not_an_object_id_is_left_out(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b]
    a, b = await _videos(video_factory, "a", "b")
    await series_factory("Show", a, b)

    # When "not-an-id" and a are assigned to "Show", in that order
    await SeriesService().assign("Show", ["not-an-id", str(a.id)])

    # Then "Show" is stored as [a, b]
    assert await stored_series("Show") == ["a", "b"]


# -----------------------------------------------------------------------
# ------- a mixed selection: members, migrants and unassigned videos -----
# -----------------------------------------------------------------------

async def test_a_mixed_selection_fills_its_own_slots_then_appends_the_newcomers(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)
    # And series "Other" stored as [x, y]
    x, y = await _videos(video_factory, "x", "y")
    await series_factory("Other", x, y)
    # And video n in no series
    n = await video_factory(name="n")

    # When c, b, x, n are assigned to "Show" in that order
    await SeriesService().assign("Show", _ids(c, b, x, n))

    # Then "Show" is stored as [a, c, b, x, n]
    assert await stored_series("Show") == ["a", "c", "b", "x", "n"]


async def test_the_requested_sequence_survives_when_a_newcomer_sits_between_members(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)
    # And video n in no series
    n = await video_factory(name="n")

    # When c, n, b are assigned to "Show" in that order
    await SeriesService().assign("Show", _ids(c, n, b))

    # Then "Show" is stored as [a, c, n, b]
    assert await stored_series("Show") == ["a", "c", "n", "b"]


async def test_a_series_the_selection_left_no_longer_lists_the_departed_videos(
    video_factory, series_factory
):
    # Given series "Other" stored as [v1, v2, v3, v4, v5]
    v1, v2, v3, v4, v5 = await _videos(video_factory, "v1", "v2", "v3", "v4", "v5")
    await series_factory("Other", v1, v2, v3, v4, v5)

    # When v2, v4 are assigned to "Show"
    await SeriesService().assign("Show", _ids(v2, v4))

    # Then "Other" is stored as [v1, v3, v5]
    assert await stored_series("Other") == ["v1", "v3", "v5"]
    # And v2 and v4 reference "Show" by seriesId
    assert await series_name_of(v2) == "Show"
    assert await series_name_of(v4) == "Show"


async def test_every_donor_series_loses_its_departed_videos_when_the_selection_spans_several(
    video_factory, series_factory
):
    # Given series "A" stored as [a1, a2, a3]
    a1, a2, a3 = await _videos(video_factory, "a1", "a2", "a3")
    await series_factory("A", a1, a2, a3)
    # And series "B" stored as [b1, b2, b3]
    b1, b2, b3 = await _videos(video_factory, "b1", "b2", "b3")
    await series_factory("B", b1, b2, b3)

    # When a2, b1 are assigned to "Show"
    await SeriesService().assign("Show", _ids(a2, b1))

    # Then "A" is stored as [a1, a3]
    assert await stored_series("A") == ["a1", "a3"]
    # And "B" is stored as [b2, b3]
    assert await stored_series("B") == ["b2", "b3"]


async def test_a_donor_series_emptied_by_the_selection_is_deleted(
    video_factory, series_factory
):
    # Given series "Other" stored as [x, y]
    x, y = await _videos(video_factory, "x", "y")
    await series_factory("Other", x, y)

    # When x, y are assigned to "Show"
    await SeriesService().assign("Show", _ids(x, y))

    # Then no series named "Other" exists
    assert await stored_series("Other") is None
    # And "Show" is stored as [x, y]
    assert await stored_series("Show") == ["x", "y"]


async def test_the_target_series_does_not_list_a_member_twice_after_a_reorder(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)

    # When c, a are assigned to "Show" in that order
    await SeriesService().assign("Show", _ids(c, a))

    # Then "Show" is stored as [c, b, a]
    assert await stored_series("Show") == ["c", "b", "a"]


async def test_a_series_outside_the_selection_is_left_untouched(
    video_factory, series_factory
):
    # Given series "Show" stored as [s1]
    s1 = await video_factory(name="s1")
    await series_factory("Show", s1)
    # And series "Other" stored as [x, y]
    x, y = await _videos(video_factory, "x", "y")
    await series_factory("Other", x, y)
    # And series "Untouched" stored as [z]
    z = await video_factory(name="z")
    await series_factory("Untouched", z)

    # When x is assigned to "Show"
    await SeriesService().assign("Show", _ids(x))

    # Then "Untouched" is still stored as [z]
    assert await stored_series("Untouched") == ["z"]
    # And z still references "Untouched" by seriesId
    assert await series_name_of(z) == "Untouched"


# -----------------------------------------------------------------------
# ------------------------- reporting a change ---------------------------
# -----------------------------------------------------------------------

async def test_an_assignment_that_changes_nothing_reports_no_change(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    show = await series_factory("Show", a, b, c)

    # When a, b, c are assigned to "Show" in that same order
    change = await SeriesService().assign("Show", _ids(a, b, c))

    # Then the assignment reports that nothing changed
    assert change.changed is False
    # And it reports the id of "Show"
    assert change.series_id == show.id


async def test_an_assignment_that_only_reorders_reports_a_change(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)

    # When b, a are assigned to "Show" in that order
    change = await SeriesService().assign("Show", _ids(b, a))

    # Then the assignment reports a change
    assert change.changed is True


# -----------------------------------------------------------------------
# ----------------------- clearing a selection ---------------------------
# -----------------------------------------------------------------------

async def test_clearing_a_selection_removes_it_from_its_series(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c, d]
    a, b, c, d = await _videos(video_factory, "a", "b", "c", "d")
    await series_factory("Show", a, b, c, d)

    # When b, d are cleared
    await SeriesService().clear(_ids(b, d))

    # Then "Show" is stored as [a, c]
    assert await stored_series("Show") == ["a", "c"]
    # And b and d reference no series
    assert await series_name_of(b) is None
    assert await series_name_of(d) is None


async def test_clearing_a_selection_that_spans_series_removes_it_from_each_of_them(
    video_factory, series_factory
):
    # Given series "A" stored as [a1, a2, a3]
    a1, a2, a3 = await _videos(video_factory, "a1", "a2", "a3")
    await series_factory("A", a1, a2, a3)
    # And series "B" stored as [b1, b2]
    b1, b2 = await _videos(video_factory, "b1", "b2")
    await series_factory("B", b1, b2)

    # When a1, b2 are cleared
    await SeriesService().clear(_ids(a1, b2))

    # Then "A" is stored as [a2, a3]
    assert await stored_series("A") == ["a2", "a3"]
    # And "B" is stored as [b1]
    assert await stored_series("B") == ["b1"]


async def test_clearing_the_last_member_deletes_the_series(video_factory, series_factory):
    # Given series "Solo" stored as [s]
    s = await video_factory(name="s")
    await series_factory("Solo", s)

    # When s is cleared
    await SeriesService().clear(_ids(s))

    # Then no series named "Solo" exists
    assert await stored_series("Solo") is None


async def test_clearing_videos_in_no_series_reports_no_change(video_factory):
    # Given videos n1, n2 in no series
    n1, n2 = await _videos(video_factory, "n1", "n2")

    # When n1, n2 are cleared
    change = await SeriesService().clear(_ids(n1, n2))

    # Then the clear reports that nothing changed
    assert change.changed is False


# -----------------------------------------------------------------------
# ------------------ detaching videos that were deleted ------------------
# -----------------------------------------------------------------------

async def test_detaching_deleted_videos_removes_their_ids_from_their_series(
    video_factory, series_factory
):
    # Given series "A" stored as [a1, a2, a3]
    a1, a2, a3 = await _videos(video_factory, "a1", "a2", "a3")
    await series_factory("A", a1, a2, a3)
    # And series "B" stored as [b1, b2]
    b1, b2 = await _videos(video_factory, "b1", "b2")
    await series_factory("B", b1, b2)
    # And a2 and b1 have been deleted from the videos collection
    await a2.delete()
    await b1.delete()

    # When a2, b1 are detached
    await SeriesService().detach(_ids(a2, b1))

    # Then "A" is stored as [a1, a3]
    assert await stored_series("A") == ["a1", "a3"]
    # And "B" is stored as [b2]
    assert await stored_series("B") == ["b2"]


async def test_detaching_the_last_member_of_a_series_deletes_the_series(
    video_factory, series_factory
):
    # Given series "Solo" stored as [s]
    s = await video_factory(name="s")
    await series_factory("Solo", s)
    # And s has been deleted from the videos collection
    await s.delete()

    # When s is detached
    await SeriesService().detach(_ids(s))

    # Then no series named "Solo" exists
    assert await stored_series("Solo") is None
