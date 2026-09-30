"""Unit tests for SeriesService — name search, listing a series, and reading positions."""

import pytest
from bson import ObjectId

from src.features.catalog.series_service import SeriesService

pytestmark = pytest.mark.unit


@pytest.fixture
def make_series(video_factory, series_factory):
    """Create a series with one member of its own, so every name belongs to a real series."""
    async def _make(*names):
        for name in names:
            member = await video_factory(name=f"member of {name}")
            await series_factory(name, member)
    return _make


# -----------------------------------------------------------------------
# ----------------------- search_by_prefix -------------------------------
# -----------------------------------------------------------------------

async def test_search_returns_matching_prefixes(make_series):
    # Given series named "MyShow", "MyShow2" and "Another"
    await make_series("MyShow", "MyShow2", "Another")

    # When series names are searched for "My"
    result = await SeriesService().search_by_prefix("My", limit=10)

    # Then "MyShow" and "MyShow2" are returned
    assert set(result) == {"MyShow", "MyShow2"}


async def test_search_is_case_insensitive(make_series):
    # Given a series named "UpperCase"
    await make_series("UpperCase")

    # When series names are searched for "upper"
    result = await SeriesService().search_by_prefix("upper", limit=10)

    # Then exactly "UpperCase" is returned
    assert result == ["UpperCase"]


async def test_search_empty_prefix_returns_all(make_series):
    # Given series named "Alpha" and "Beta"
    await make_series("Alpha", "Beta")

    # When series names are searched for ""
    result = await SeriesService().search_by_prefix("", limit=10)

    # Then "Alpha" and "Beta" are returned
    assert set(result) == {"Alpha", "Beta"}


async def test_search_matches_middle_and_suffix(make_series):
    # Given series named "Dragon Ball", "The Ball Game", "Pinball" and "Unrelated"
    await make_series("Dragon Ball", "The Ball Game", "Pinball", "Unrelated")

    # When series names are searched for "ball"
    result = await SeriesService().search_by_prefix("ball", limit=10)

    # Then "Dragon Ball", "The Ball Game" and "Pinball" are returned
    assert set(result) == {"Dragon Ball", "The Ball Game", "Pinball"}


async def test_prefix_matches_rank_before_contains_matches(make_series):
    # Given series named "Showdown", "Amazing Show" and "Show Time"
    await make_series("Showdown", "Amazing Show", "Show Time")

    # When series names are searched for "show"
    result = await SeriesService().search_by_prefix("show", limit=10)

    # Then the result is exactly ["Show Time", "Showdown", "Amazing Show"]
    assert result == ["Show Time", "Showdown", "Amazing Show"]


async def test_search_respects_limit(make_series):
    # Given series named "S0" through "S4"
    await make_series(*[f"S{i}" for i in range(5)])

    # When series names are searched for "S" with a limit of 3
    result = await SeriesService().search_by_prefix("S", limit=3)

    # Then 3 names are returned
    assert len(result) == 3


async def test_limit_trims_contains_matches_before_prefix_matches(make_series):
    # Given series named "Arc Two" and "Two Arcs"
    await make_series("Arc Two", "Two Arcs")

    # When series names are searched for "two" with a limit of 1
    result = await SeriesService().search_by_prefix("two", limit=1)

    # Then the result is exactly ["Two Arcs"]
    assert result == ["Two Arcs"]


async def test_search_escapes_regex_metacharacters(make_series):
    # Given series named "Season 1.5" and "Season 145"
    await make_series("Season 1.5", "Season 145")

    # When series names are searched for "1.5"
    result = await SeriesService().search_by_prefix("1.5", limit=10)

    # Then the result is exactly ["Season 1.5"]
    assert result == ["Season 1.5"]


# -----------------------------------------------------------------------
# ----------------------- get_videos_in_series ---------------------------
# -----------------------------------------------------------------------

async def test_get_videos_in_series_follows_the_stored_order(video_factory, series_factory):
    # Given series "Show" stored as [ep2, ep1, ep3]
    ep1 = await video_factory(name="ep1")
    ep2 = await video_factory(name="ep2")
    ep3 = await video_factory(name="ep3")
    await series_factory("Show", ep2, ep1, ep3)

    # When the videos of "Show" are listed
    videos = await SeriesService().get_videos_in_series("Show", ["Test-category"])

    # Then they come back as ep2, ep1, ep3
    assert [v.name for v in videos] == ["ep2", "ep1", "ep3"]


async def test_get_videos_in_series_filters_by_category(video_factory, series_factory):
    # Given series "S" stored as [v], where v is in "Test-category"
    v = await video_factory(name="in", category="Test-category")
    await series_factory("S", v)
    svc = SeriesService()

    # When the videos of "S" are listed for category "Test-category"
    # Then v is returned
    assert [x.name for x in await svc.get_videos_in_series("S", ["Test-category"])] == ["in"]
    # When the videos of "S" are listed for category "Other"
    # Then nothing is returned
    assert await svc.get_videos_in_series("S", ["Other"]) == []


async def test_get_videos_in_series_skips_ids_with_no_video_behind_them(
    video_factory, series_factory
):
    # Given series "Show" stored as [a, <an id with no video>, b]
    a = await video_factory(name="a")
    b = await video_factory(name="b")
    show = await series_factory("Show", a, b)
    show.videoIds.insert(1, ObjectId("507f1f77bcf86cd799439011"))
    await show.save()

    # When the videos of "Show" are listed
    videos = await SeriesService().get_videos_in_series("Show", ["Test-category"])

    # Then they come back as a, b
    assert [v.name for v in videos] == ["a", "b"]


async def test_get_videos_in_series_returns_empty_for_missing(init_db):
    # Given no series named "NonExistent"
    # When the videos of "NonExistent" are listed
    videos = await SeriesService().get_videos_in_series("NonExistent", ["Test-category"])

    # Then nothing is returned
    assert videos == []


async def test_get_videos_returns_empty_for_empty_name(init_db):
    # When the videos of "" are listed
    videos = await SeriesService().get_videos_in_series("", ["Test-category"])

    # Then nothing is returned
    assert videos == []


async def test_get_videos_returns_empty_for_empty_categories(video_factory, series_factory):
    # Given series "S" stored as [v]
    v = await video_factory(name="v")
    await series_factory("S", v)

    # When the videos of "S" are listed with no valid categories
    videos = await SeriesService().get_videos_in_series("S", [])

    # Then nothing is returned
    assert videos == []


# -----------------------------------------------------------------------
# --------------------------- positions_of -------------------------------
# -----------------------------------------------------------------------

def _as_pair(placement):
    return (placement.series_name, placement.order)


async def test_positions_of_reads_name_and_one_based_order_for_each_video(
    video_factory, series_factory
):
    # Given series "A" stored as [a1, a2, a3]
    a1 = await video_factory(name="a1")
    a2 = await video_factory(name="a2")
    a3 = await video_factory(name="a3")
    await series_factory("A", a1, a2, a3)
    # And series "B" stored as [b1, b2]
    b1 = await video_factory(name="b1")
    b2 = await video_factory(name="b2")
    await series_factory("B", b1, b2)

    # When the positions of a3, b1 and a1 are read
    positions = await SeriesService().positions_of([a3, b1, a1])

    # Then a3 is ("A", 3), b1 is ("B", 1) and a1 is ("A", 1)
    assert _as_pair(positions[str(a3.id)]) == ("A", 3)
    assert _as_pair(positions[str(b1.id)]) == ("B", 1)
    assert _as_pair(positions[str(a1.id)]) == ("A", 1)


async def test_positions_of_leaves_out_videos_in_no_series(video_factory, series_factory):
    # Given series "A" stored as [a1]
    a1 = await video_factory(name="a1")
    await series_factory("A", a1)
    # And video n in no series
    n = await video_factory(name="n")

    # When the positions of a1 and n are read
    positions = await SeriesService().positions_of([a1, n])

    # Then a1 has a position
    assert str(a1.id) in positions
    # And n has none
    assert str(n.id) not in positions


async def test_positions_of_a_video_whose_series_is_gone_is_absent(video_factory):
    # Given video v whose seriesId references a series that no longer exists
    v = await video_factory(name="v", seriesId=ObjectId("507f1f77bcf86cd799439011"))

    # When the position of v is read
    positions = await SeriesService().positions_of([v])

    # Then v has no position
    assert positions == {}
