"""Unit tests for SeriesService — prefix search, reorder, and series management."""

import pytest

from src.features.catalog.series_service import SeriesService

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# ----------------------- search_by_prefix -------------------------------
# -----------------------------------------------------------------------

async def test_search_returns_matching_prefixes(init_db, video_factory):
    await video_factory(name="ep1", seriesName="MyShow")
    await video_factory(name="ep2", seriesName="MyShow2")
    await video_factory(name="ep3", seriesName="Another")

    svc = SeriesService()
    result = await svc.search_by_prefix("My", limit=10)
    assert set(result) == {"MyShow", "MyShow2"}


async def test_search_is_case_insensitive(init_db, video_factory):
    await video_factory(name="v", seriesName="UpperCase")

    svc = SeriesService()
    result = await svc.search_by_prefix("upper", limit=10)
    assert result == ["UpperCase"]


async def test_search_empty_prefix_returns_all(init_db, video_factory):
    await video_factory(name="a", seriesName="Alpha")
    await video_factory(name="b", seriesName="Beta")

    svc = SeriesService()
    result = await svc.search_by_prefix("", limit=10)
    assert set(result) == {"Alpha", "Beta"}


async def test_search_matches_middle_and_suffix(init_db, video_factory):
    await video_factory(name="a", seriesName="Dragon Ball")
    await video_factory(name="b", seriesName="The Ball Game")
    await video_factory(name="c", seriesName="Pinball")
    await video_factory(name="d", seriesName="Unrelated")

    svc = SeriesService()
    result = await svc.search_by_prefix("ball", limit=10)
    assert set(result) == {"Dragon Ball", "The Ball Game", "Pinball"}


async def test_prefix_matches_rank_before_contains_matches(init_db, video_factory):
    await video_factory(name="a", seriesName="Showdown")      # prefix match
    await video_factory(name="b", seriesName="Amazing Show")  # contains match, sorts first
    await video_factory(name="c", seriesName="Show Time")     # prefix match

    svc = SeriesService()
    result = await svc.search_by_prefix("show", limit=10)
    # Both prefix matches come first (alphabetically), then the contains match —
    # even though "Amazing Show" would sort ahead of them overall.
    assert result == ["Show Time", "Showdown", "Amazing Show"]


async def test_search_respects_limit(init_db, video_factory):
    for i in range(5):
        await video_factory(name=f"v{i}", seriesName=f"S{i}")

    svc = SeriesService()
    result = await svc.search_by_prefix("S", limit=3)
    assert len(result) == 3


async def test_limit_trims_contains_matches_before_prefix_matches(init_db, video_factory):
    await video_factory(name="a", seriesName="Arc Two")   # contains match
    await video_factory(name="b", seriesName="Two Arcs")  # prefix match

    svc = SeriesService()
    result = await svc.search_by_prefix("two", limit=1)
    assert result == ["Two Arcs"]


async def test_search_escapes_regex_metacharacters(init_db, video_factory):
    await video_factory(name="a", seriesName="Season 1.5")
    await video_factory(name="b", seriesName="Season 145")

    svc = SeriesService()
    result = await svc.search_by_prefix("1.5", limit=10)
    assert result == ["Season 1.5"]


async def test_search_excludes_null_series(init_db, video_factory):
    await video_factory(name="no-series", seriesName=None)
    await video_factory(name="has-series", seriesName="Real")

    svc = SeriesService()
    result = await svc.search_by_prefix("", limit=10)
    assert result == ["Real"]


# -----------------------------------------------------------------------
# ----------------------- get_videos_in_series ---------------------------
# -----------------------------------------------------------------------

async def test_get_videos_in_series_sorted_by_order(init_db, video_factory):
    await video_factory(name="ep2", seriesName="Show", seriesOrder=2)
    await video_factory(name="ep1", seriesName="Show", seriesOrder=1)

    svc = SeriesService()
    videos = await svc.get_videos_in_series("Show", ["Test-category"])

    assert [v.name for v in videos] == ["ep1", "ep2"]


async def test_get_videos_in_series_filters_by_category(init_db, video_factory):
    await video_factory(name="in", seriesName="S", category="Test-category")

    svc = SeriesService()
    assert len(await svc.get_videos_in_series("S", ["Test-category"])) == 1
    assert len(await svc.get_videos_in_series("S", ["Other"])) == 0


async def test_get_videos_in_series_returns_empty_for_missing(init_db):
    svc = SeriesService()
    assert await svc.get_videos_in_series("NonExistent", ["Test-category"]) == []


async def test_get_videos_returns_empty_for_empty_name(init_db):
    svc = SeriesService()
    assert await svc.get_videos_in_series("", ["Test-category"]) == []


async def test_get_videos_returns_empty_for_empty_categories(init_db, video_factory):
    await video_factory(name="v", seriesName="S")
    svc = SeriesService()
    assert await svc.get_videos_in_series("S", []) == []
