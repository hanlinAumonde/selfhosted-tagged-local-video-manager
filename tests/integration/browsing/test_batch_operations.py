"""Batch edits and deletes chosen in the file browser: every selected video has to change,
the unselected ones must not, and the rest of the app has to see the result.
"""

from tests.integration.graphql_documents import (
    BATCH_DELETE_SUBSCRIPTION,
    BATCH_UPDATE_SUBSCRIPTION,
    GET_SERIES_VIDEOS,
    GET_VIDEO_BY_ID,
    SEARCH_SERIES_BY_PREFIX,
)
from tests.integration.helpers import (
    DRAMA_DIR,
    RESOURCE_DIR,
    assert_no_errors,
    browse_nodes,
    discover_videos,
    make_batch_input,
    searched_names,
    top_tags,
    update_video,
)


def _assert_batch_succeeded(events: list, field: str) -> None:
    for event in events:
        assert_no_errors(event)
    assert events[-1].data[field]["result"]["resultType"] == "Success"


class TestBatchEdit:
    async def test_batch_tag_and_author_edit_reaches_every_selected_video(
        self, execute_gql, subscribe_gql, init_db,
    ):
        """
        Given alpha, beta, charlie and delta discovered by browsing
        And beta tagged "todo", charlie tagged "todo" and "keep", alpha untagged
        When one batch update on alpha, beta and charlie adds "4k", removes "todo"
             and sets the author "BatchAuthor"
        Then searching the tag "4k" returns exactly alpha, beta and charlie
        And searching the author "BatchAuthor" returns exactly alpha, beta and charlie
        And the top tags list "4k" with count 3 and "keep" with count 1, and no "todo"
        And delta keeps no tags and the default author "Unknown"
        """
        ids = await discover_videos(execute_gql, RESOURCE_DIR, DRAMA_DIR)
        await update_video(execute_gql, ids["beta"], tags=["todo"])
        await update_video(execute_gql, ids["charlie"], tags=["todo", "keep"])

        events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": make_batch_input(
            [ids["alpha"], ids["beta"], ids["charlie"]],
            RESOURCE_DIR,
            tagsOperation={"addTags": ["4k"], "removeTags": ["todo"]},
            author="BatchAuthor",
        )})

        _assert_batch_succeeded(events, "batchUpdateSubscription")
        selected = ["alpha", "beta", "charlie"]
        assert await searched_names(execute_gql, tags=["4k"]) == (selected, 3)
        assert await searched_names(execute_gql, author={"keyWord": "BatchAuthor"}) == (selected, 3)
        assert await top_tags(execute_gql) == {"4k": 3, "keep": 1}
        delta = await execute_gql(GET_VIDEO_BY_ID, {"videoId": ids["delta"]})
        assert_no_errors(delta)
        assert (delta.data["getVideoById"]["tags"], delta.data["getVideoById"]["author"]) == ([], "Unknown")

    async def test_batch_series_assignment_moves_videos_out_of_their_old_series(
        self, execute_gql, subscribe_gql, init_db,
    ):
        """
        Given alpha, beta and charlie discovered by browsing
        And alpha the only member of the series "Old"
        When one batch update assigns charlie, alpha, beta (in that order) to the series "Saga"
        Then the series "Saga" lists charlie, alpha, beta with orders 1, 2, 3
        And getVideoById reports alpha in "Saga" at order 2
        And no series named "Old" is suggested any more
        """
        ids = await discover_videos(execute_gql, RESOURCE_DIR, DRAMA_DIR)
        await update_video(execute_gql, ids["alpha"], series={
            "name": "Old", "clear": False, "orders": [{"videoId": ids["alpha"], "order": 1}],
        })

        events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": make_batch_input(
            [ids["charlie"], ids["alpha"], ids["beta"]],
            RESOURCE_DIR,
            seriesOperation={"name": "Saga", "clear": False, "orders": [
                {"videoId": ids["charlie"], "order": 1},
                {"videoId": ids["alpha"], "order": 2},
                {"videoId": ids["beta"], "order": 3},
            ]},
        )})

        _assert_batch_succeeded(events, "batchUpdateSubscription")
        saga = await execute_gql(GET_SERIES_VIDEOS, {"name": "Saga"})
        assert_no_errors(saga)
        assert [(v["name"], v["seriesOrder"]) for v in saga.data["getSeriesVideos"]] == [
            ("charlie", 1), ("alpha", 2), ("beta", 3),
        ]
        alpha = await execute_gql(GET_VIDEO_BY_ID, {"videoId": ids["alpha"]})
        assert_no_errors(alpha)
        assert (alpha.data["getVideoById"]["seriesName"], alpha.data["getVideoById"]["seriesOrder"]) == ("Saga", 2)
        old = await execute_gql(SEARCH_SERIES_BY_PREFIX, {"prefix": "Old", "limit": 5})
        assert_no_errors(old)
        assert old.data["searchSeriesByPrefix"] == []


class TestBatchDelete:
    # A selection spanning sub-directories comes from searchInDirectory results.
    async def test_batch_delete_removes_files_records_and_rows_in_both_directories(
        self, execute_gql, subscribe_gql, init_db, integration_resource_dir,
    ):
        """
        Given alpha, beta, charlie and delta discovered by browsing
        When one batch delete removes alpha (in Test-resource) and charlie (in drama)
        Then alpha.mp4 and drama/charlie.mp4 are gone from disk, beta.mp4 and drama/delta.mp4 remain
        And Test-resource lists exactly beta and drama, with drama at 4000 bytes
        And drama lists exactly delta
        And searching all videos returns exactly beta and delta
        """
        ids = await discover_videos(execute_gql, RESOURCE_DIR, DRAMA_DIR)

        events = await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": make_batch_input(
            [ids["alpha"], ids["charlie"]], RESOURCE_DIR,
        )})

        _assert_batch_succeeded(events, "batchDeleteSubscription")
        assert not (integration_resource_dir / "alpha.mp4").exists()
        assert not (integration_resource_dir / "drama" / "charlie.mp4").exists()
        assert (integration_resource_dir / "beta.mp4").exists()
        assert (integration_resource_dir / "drama" / "delta.mp4").exists()
        resource = await browse_nodes(execute_gql, RESOURCE_DIR)
        assert {name: node["size"] for name, node in resource.items()} == {"beta": 2000, "drama": 4000}
        assert list(await browse_nodes(execute_gql, DRAMA_DIR)) == ["delta"]
        assert await searched_names(execute_gql) == (["beta", "delta"], 2)
