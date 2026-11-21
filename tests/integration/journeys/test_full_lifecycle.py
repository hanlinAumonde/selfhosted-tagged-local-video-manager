"""One user session across browsing, the catalogue, playback bookkeeping and tags."""

from tests.integration.graphql_documents import DELETE_VIDEO, GET_VIDEO_BY_ID, RECORD_VIDEO_VIEW
from tests.integration.helpers import (
    RESOURCE_DIR,
    assert_no_errors,
    discover_videos,
    searched_names,
    top_tags,
    update_video,
)


class TestFullLifecycle:
    async def test_a_session_from_discovery_to_deletion(
        self, execute_gql, init_db, integration_resource_dir,
    ):
        """
        Given the resource tree browsed at Test-category/Test-resource
        When alpha is renamed "Alpha Prime", given the author "Director X", loved,
             and tagged "action" and "sci-fi"
        And its view is recorded twice
        Then getVideoById reports alpha with view count 2
        And searching the author "Director X" returns exactly "Alpha Prime"
        And searching the tag "sci-fi" returns exactly "Alpha Prime"
        And the Loved sort returns exactly "Alpha Prime"
        When "Alpha Prime" is deleted
        Then alpha.mp4 is gone from disk
        And searching all videos returns exactly beta
        And the top tags list neither "action" nor "sci-fi"
        """
        alpha_id = (await discover_videos(execute_gql, RESOURCE_DIR))["alpha"]

        await update_video(
            execute_gql, alpha_id,
            name="Alpha Prime", author="Director X", loved=True, tags=["action", "sci-fi"],
        )
        for _ in range(2):
            assert_no_errors(await execute_gql(RECORD_VIDEO_VIEW, {"videoId": alpha_id}))

        viewed = await execute_gql(GET_VIDEO_BY_ID, {"videoId": alpha_id})
        assert_no_errors(viewed)
        assert viewed.data["getVideoById"]["viewCount"] == 2
        assert await searched_names(execute_gql, author={"keyWord": "Director X"}) == (["Alpha Prime"], 1)
        assert await searched_names(execute_gql, tags=["sci-fi"]) == (["Alpha Prime"], 1)
        assert await searched_names(execute_gql, sortBy="Loved") == (["Alpha Prime"], 1)

        deleted = await execute_gql(DELETE_VIDEO, {"videoId": alpha_id})
        assert_no_errors(deleted)

        assert not (integration_resource_dir / "alpha.mp4").exists()
        assert await searched_names(execute_gql) == (["beta"], 1)
        assert await top_tags(execute_gql) == {}
