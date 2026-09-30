"""
Behaviour specification — ``Video.seriesName`` / ``Video.seriesOrder`` on the published schema.

The database no longer stores either field: a video only holds a ``seriesId``, and its
position is its index in that series' ``videoIds``. The schema keeps publishing both
fields unchanged, so every query that returns a ``Video`` has to derive them — and the
frontend, which reads them on every one of those queries, must not be able to tell.
"""

import pytest

from src.features.browsing.browse_file_service import VideoEntry
from tests.graphql.helpers import (
    assert_no_errors,
    make_relative_path_input,
    make_search_input,
    make_update_input,
)

pytestmark = pytest.mark.query


GET_VIDEO_SERIES = """
query GetVideoById($videoId: ID!) {
  getVideoById(videoId: $videoId) { name seriesName seriesOrder }
}
"""

SEARCH_VIDEOS_SERIES = """
query SearchVideos($input: VideoSearchInput!) {
  SearchVideos(input: $input) { videos { name seriesName seriesOrder } }
}
"""

BROWSE_DIRECTORY_SERIES = """
query BrowseDirectory($input: RelativePathInput!) {
  browseDirectory(input: $input) { node { name seriesName seriesOrder } }
}
"""

GET_SERIES_VIDEOS_SERIES = """
query GetSeriesVideos($name: String!) {
  getSeriesVideos(name: $name) { name seriesName seriesOrder }
}
"""

UPDATE_VIDEO_SERIES = """
mutation UpdateVideoMetadata($input: UpdateVideoMetadataInput!) {
  updateVideoMetadata(input: $input) { success video { name seriesName seriesOrder } }
}
"""


def _pair(row) -> tuple:
    return (row["seriesName"], row["seriesOrder"])


async def test_get_video_by_id_publishes_the_series_name_and_one_based_order(
    execute_gql, video_factory, series_factory
):
    # Given series "Show" stored as [a, b, c]
    a = await video_factory(name="a")
    b = await video_factory(name="b")
    c = await video_factory(name="c")
    await series_factory("Show", a, b, c)

    # When getVideoById is queried for c
    result = await execute_gql(GET_VIDEO_SERIES, {"videoId": str(c.id)})

    # Then its seriesName is "Show" and its seriesOrder is 3
    assert_no_errors(result)
    assert _pair(result.data["getVideoById"]) == ("Show", 3)


async def test_a_video_in_no_series_publishes_null_series_fields(execute_gql, video_factory):
    # Given video n in no series
    n = await video_factory(name="n")

    # When getVideoById is queried for n
    result = await execute_gql(GET_VIDEO_SERIES, {"videoId": str(n.id)})

    # Then its seriesName and seriesOrder are both null
    assert_no_errors(result)
    assert _pair(result.data["getVideoById"]) == (None, None)


async def test_search_videos_publishes_series_fields_for_every_row(
    execute_gql, video_factory, series_factory
):
    # Given series "A" stored as [a1, a2]
    a1 = await video_factory(name="a1")
    a2 = await video_factory(name="a2")
    await series_factory("A", a1, a2)
    # And series "B" stored as [b1]
    b1 = await video_factory(name="b1")
    await series_factory("B", b1)
    # And video n in no series
    await video_factory(name="n")

    # When searchVideos lists all four videos
    result = await execute_gql(SEARCH_VIDEOS_SERIES, {"input": make_search_input()})

    # Then a2 is ("A", 2), b1 is ("B", 1), a1 is ("A", 1) and n is (null, null)
    assert_no_errors(result)
    rows = {row["name"]: _pair(row) for row in result.data["SearchVideos"]["videos"]}
    assert rows == {
        "a1": ("A", 1),
        "a2": ("A", 2),
        "b1": ("B", 1),
        "n": (None, None),
    }


async def test_browse_directory_publishes_series_fields_for_every_video_row(
    execute_gql, video_factory, series_factory, mock_browse_file_service
):
    # Given series "Show" stored as [first, second], both files in the browsed directory
    first = await video_factory(name="first")
    second = await video_factory(name="second")
    await series_factory("Show", first, second)
    mock_browse_file_service.get_node_list_in_directory.return_value = [
        VideoEntry(document=second, is_locked=False),
        VideoEntry(document=first, is_locked=False),
    ]

    # When browseDirectory lists that directory
    result = await execute_gql(
        BROWSE_DIRECTORY_SERIES,
        {"input": make_relative_path_input("Test-category/Test-resource")},
    )

    # Then first is ("Show", 1) and second is ("Show", 2)
    assert_no_errors(result)
    rows = {r["node"]["name"]: _pair(r["node"]) for r in result.data["browseDirectory"]}
    assert rows == {"first": ("Show", 1), "second": ("Show", 2)}


async def test_get_series_videos_publishes_orders_matching_the_listed_sequence(
    execute_gql, video_factory, series_factory
):
    # Given series "Show" stored as [ep2, ep1]
    ep1 = await video_factory(name="ep1")
    ep2 = await video_factory(name="ep2")
    await series_factory("Show", ep2, ep1)

    # When getSeriesVideos is queried for "Show"
    result = await execute_gql(GET_SERIES_VIDEOS_SERIES, {"name": "Show"})

    # Then the rows are ep2 with seriesOrder 1, then ep1 with seriesOrder 2
    assert_no_errors(result)
    rows = [(r["name"], r["seriesOrder"]) for r in result.data["getSeriesVideos"]]
    assert rows == [("ep2", 1), ("ep1", 2)]


async def test_update_video_metadata_returns_the_new_series_fields(
    execute_gql, video_factory, series_factory
):
    # Given series "Show" stored as [a, b]
    a = await video_factory(name="a")
    b = await video_factory(name="b")
    await series_factory("Show", a, b)

    # When updateVideoMetadata moves b to the front of "Show"
    result = await execute_gql(UPDATE_VIDEO_SERIES, {"input": make_update_input(
        str(b.id),
        series={
            "name": "Show",
            "clear": False,
            "orders": [
                {"videoId": str(b.id), "order": 1},
                {"videoId": str(a.id), "order": 2},
            ],
        },
    )})

    # Then the returned video has seriesName "Show" and seriesOrder 1
    assert_no_errors(result)
    assert _pair(result.data["updateVideoMetadata"]["video"]) == ("Show", 1)
