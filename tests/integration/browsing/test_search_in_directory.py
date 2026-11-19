"""Searching inside a directory: the catalogue decides what matches, the disk decides what
is still there, and each hit says which sub-directory it was found in.
"""

from src.features.catalog.video import VideoModel
from tests.integration.graphql_documents import SEARCH_IN_DIRECTORY
from tests.integration.helpers import (
    DRAMA_DIR,
    RESOURCE_DIR,
    assert_no_errors,
    browse_nodes,
    discover_videos,
    make_browse_input,
    update_video,
)


async def _search(execute_gql, *, name=None, tags=()) -> list[tuple[str, str | None]]:
    """Search Test-resource and its sub-directories; returns sorted (name, found in) pairs."""
    result = await execute_gql(SEARCH_IN_DIRECTORY, {"input": {
        "path": make_browse_input(RESOURCE_DIR),
        "name": {"keyWord": name},
        "author": {"keyWord": None},
        "tags": list(tags),
    }})
    assert_no_errors(result)
    return sorted(
        (row["node"]["name"], row["node"]["relativePath"])
        for row in result.data["searchInDirectory"]
    )


class TestSearchInDirectory:
    async def test_matches_in_sub_directories_come_back_with_their_location(
        self, execute_gql, init_db,
    ):
        """
        Given alpha, beta, charlie and delta discovered by browsing
        And alpha and charlie tagged "hero" through GraphQL
        When Test-resource is searched for the tag "hero"
        Then the result is exactly alpha, found in Test-resource itself,
             and charlie, found in "drama"
        """
        ids = await discover_videos(execute_gql, RESOURCE_DIR, DRAMA_DIR)
        await update_video(execute_gql, ids["alpha"], tags=["hero"])
        await update_video(execute_gql, ids["charlie"], tags=["hero"])

        assert await _search(execute_gql, tags=["hero"]) == [("alpha", None), ("charlie", "drama")]

    async def test_a_record_whose_file_left_the_disk_is_not_returned(
        self, execute_gql, init_db, integration_resource_dir,
    ):
        """
        Given alpha and beta discovered by browsing and both tagged "hero"
        And alpha.mp4 then removed from disk outside the app
        When Test-resource is searched for the tag "hero"
        Then the result is exactly beta
        """
        ids = await discover_videos(execute_gql, RESOURCE_DIR)
        await update_video(execute_gql, ids["alpha"], tags=["hero"])
        await update_video(execute_gql, ids["beta"], tags=["hero"])
        (integration_resource_dir / "alpha.mp4").unlink()

        assert await _search(execute_gql, tags=["hero"]) == [("beta", None)]

    async def test_videos_never_browsed_are_not_found_and_not_stored(
        self, execute_gql, init_db,
    ):
        """
        Given Test-resource browsed but drama never browsed
        When Test-resource is searched for the name "charlie"
        Then the result is empty
        And no video record exists for drama/charlie.mp4
        """
        await browse_nodes(execute_gql, RESOURCE_DIR)

        assert await _search(execute_gql, name="charlie") == []
        assert await VideoModel.find_one({"path": f"{DRAMA_DIR}/charlie.mp4"}) is None
