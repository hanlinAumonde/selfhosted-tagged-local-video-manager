"""Tests for the ``SearchVideos`` query."""

import pytest

from tests.graphql.helpers import (
    SEARCH_VIDEOS,
    assert_error_contains,
    assert_no_errors,
    make_search_input,
)


pytestmark = pytest.mark.query


async def test_search_videos_basic(execute_gql, video_factory):
    await video_factory(name="alpha", lastViewTime=10.0)
    await video_factory(name="beta", lastViewTime=20.0)

    result = await execute_gql(SEARCH_VIDEOS, {"input": make_search_input()})

    assert_no_errors(result)
    payload = result.data["SearchVideos"]
    assert payload["pagination"]["totalCount"] == 2
    assert {v["name"] for v in payload["videos"]} == {"alpha", "beta"}


async def test_search_videos_filter_by_title_keyword(execute_gql, video_factory):
    await video_factory(name="action-movie")
    await video_factory(name="comedy-show")

    result = await execute_gql(
        SEARCH_VIDEOS,
        {"input": make_search_input(titleKeyword={"keyWord": "action"})},
    )

    assert_no_errors(result)
    names = [v["name"] for v in result.data["SearchVideos"]["videos"]]
    assert names == ["action-movie"]


async def test_search_videos_filter_by_author(execute_gql, video_factory):
    await video_factory(name="v1", author="alice")
    await video_factory(name="v2", author="bob")

    result = await execute_gql(
        SEARCH_VIDEOS,
        {"input": make_search_input(author={"keyWord": "alice"})},
    )

    assert_no_errors(result)
    videos = result.data["SearchVideos"]["videos"]
    assert len(videos) == 1
    assert videos[0]["author"] == "alice"


async def test_search_videos_tag_all_must_match(execute_gql, video_factory):
    await video_factory(name="v1", tags=["a", "b"])
    await video_factory(name="v2", tags=["a"])
    await video_factory(name="v3", tags=["a", "b", "c"])

    result = await execute_gql(
        SEARCH_VIDEOS, {"input": make_search_input(tags=["a", "b"])}
    )

    assert_no_errors(result)
    names = sorted(v["name"] for v in result.data["SearchVideos"]["videos"])
    assert names == ["v1", "v3"]


async def test_search_videos_loved_sort_only_loved(execute_gql, video_factory):
    await video_factory(name="loved-1", loved=True, lastViewTime=10.0)
    await video_factory(name="loved-2", loved=True, lastViewTime=20.0)
    await video_factory(name="not-loved", loved=False)

    result = await execute_gql(
        SEARCH_VIDEOS, {"input": make_search_input(sortBy="Loved")}
    )

    assert_no_errors(result)
    names = [v["name"] for v in result.data["SearchVideos"]["videos"]]
    # Loved sort: most-recent lastViewTime first (DESC) — also filters out
    # non-loved videos.
    assert names == ["loved-2", "loved-1"]


async def test_search_videos_most_viewed_sort(execute_gql, video_factory):
    await video_factory(name="low", viewCount=1)
    await video_factory(name="high", viewCount=99)

    result = await execute_gql(
        SEARCH_VIDEOS, {"input": make_search_input(sortBy="MostViewed")}
    )

    assert_no_errors(result)
    names = [v["name"] for v in result.data["SearchVideos"]["videos"]]
    assert names == ["high", "low"]


async def test_search_videos_pagination_homepage_size(
    execute_gql, video_factory, test_settings
):
    homepage_size = test_settings.page_size_default.homepage_videos
    for i in range(homepage_size + 3):
        await video_factory(name=f"v{i}")

    result = await execute_gql(
        SEARCH_VIDEOS,
        {"input": make_search_input(fromPage="FrontalPage")},
    )

    assert_no_errors(result)
    payload = result.data["SearchVideos"]
    assert payload["pagination"]["size"] == homepage_size
    assert payload["pagination"]["totalCount"] == homepage_size + 3
    assert len(payload["videos"]) == homepage_size


async def test_search_videos_no_valid_categories_returns_empty(
    execute_gql, video_factory, monkeypatch, test_settings
):
    await video_factory(name="anything")
    monkeypatch.setattr(test_settings, "resource_paths", {})

    result = await execute_gql(SEARCH_VIDEOS, {"input": make_search_input()})

    assert_no_errors(result)
    payload = result.data["SearchVideos"]
    assert payload["pagination"]["totalCount"] == 0
    assert payload["videos"] == []


async def test_search_videos_calls_ffmpeg_when_duration_missing(
    execute_gql, video_factory, mock_ffmpeg_service
):
    await video_factory(name="needs-duration", duration=0.0)

    result = await execute_gql(SEARCH_VIDEOS, {"input": make_search_input()})

    assert_no_errors(result)
    mock_ffmpeg_service.get_video_duration.assert_awaited_once()
    duration = result.data["SearchVideos"]["videos"][0]["duration"]
    assert duration == 120.0


async def test_search_videos_last_update_sort(execute_gql, video_factory):
    # Given two videos where the newest on disk is the least recently viewed
    await video_factory(name="added_late", lastModifyTime=300.0, lastViewTime=100.0)
    await video_factory(name="watched_late", lastModifyTime=100.0, lastViewTime=300.0)

    # When SearchVideos is asked for sortBy "LastUpdate"
    result = await execute_gql(
        SEARCH_VIDEOS, {"input": make_search_input(sortBy="LastUpdate")}
    )

    # Then the published enum accepts it and the videos come back newest-on-disk first
    assert_no_errors(result)
    names = [v["name"] for v in result.data["SearchVideos"]["videos"]]
    assert names == ["added_late", "watched_late"]


async def test_search_videos_invalid_page_number(execute_gql, init_db):
    result = await execute_gql(
        SEARCH_VIDEOS, {"input": make_search_input(currentPageNumber=0)}
    )
    assert_error_contains(result, "VideoSearchInput")


async def test_search_videos_missing_required_input(execute_gql, init_db):
    result = await execute_gql(SEARCH_VIDEOS, {})
    assert_error_contains(result, "input")
