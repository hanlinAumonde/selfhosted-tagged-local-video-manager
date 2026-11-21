"""Deleting one video: the file, the record, its directory row, its tags and its place in
a series all have to go together.
"""

from tests.integration.graphql_documents import DELETE_VIDEO, GET_SERIES_VIDEOS
from tests.integration.helpers import (
    RESOURCE_DIR,
    assert_no_errors,
    browse_nodes,
    discover_videos,
    searched_names,
    top_tags,
    update_video,
)


async def _delete(execute_gql, video_id: str) -> None:
    result = await execute_gql(DELETE_VIDEO, {"videoId": video_id})
    assert_no_errors(result)
    assert result.data["deleteVideo"]["success"] is True


class TestDeleteVideo:
    async def test_deleted_video_is_gone_from_disk_listing_search_and_tags(
        self, execute_gql, init_db, integration_resource_dir,
    ):
        """
        Given alpha and beta discovered by browsing
        And beta tagged "to-remove" and alpha tagged "keep"
        When beta is deleted through GraphQL
        Then beta.mp4 is gone from disk and alpha.mp4 remains
        And Test-resource no longer lists beta
        And searching all videos returns exactly alpha
        And the top tags list "keep" with count 1 and no "to-remove"
        """
        ids = await discover_videos(execute_gql, RESOURCE_DIR)
        await update_video(execute_gql, ids["beta"], tags=["to-remove"])
        await update_video(execute_gql, ids["alpha"], tags=["keep"])

        await _delete(execute_gql, ids["beta"])

        assert not (integration_resource_dir / "beta.mp4").exists()
        assert (integration_resource_dir / "alpha.mp4").exists()
        assert "beta" not in await browse_nodes(execute_gql, RESOURCE_DIR)
        assert await searched_names(execute_gql) == (["alpha"], 1)
        assert await top_tags(execute_gql) == {"keep": 1}

    async def test_deleting_a_series_member_closes_the_gap(self, execute_gql, init_db):
        """
        Given alpha, beta discovered by browsing and assigned to the series "Saga" as alpha, beta
        When alpha is deleted through GraphQL
        Then the series "Saga" lists exactly beta, at order 1
        """
        ids = await discover_videos(execute_gql, RESOURCE_DIR)
        await update_video(execute_gql, ids["alpha"], series={
            "name": "Saga", "clear": False, "orders": [{"videoId": ids["alpha"], "order": 1}],
        })
        await update_video(execute_gql, ids["beta"], series={
            "name": "Saga", "clear": False, "orders": [
                {"videoId": ids["alpha"], "order": 1}, {"videoId": ids["beta"], "order": 2},
            ],
        })

        await _delete(execute_gql, ids["alpha"])

        saga = await execute_gql(GET_SERIES_VIDEOS, {"name": "Saga"})
        assert_no_errors(saga)
        assert [(v["name"], v["seriesOrder"]) for v in saga.data["getSeriesVideos"]] == [("beta", 1)]
