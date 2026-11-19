"""Browsing is how videos enter the catalogue: what is found on disk is stored once, listed
with its disk size, and from then on can be found by search.
"""

from src.features.catalog.video import VideoModel
from tests.integration.helpers import DRAMA_DIR, RESOURCE_DIR, browse_nodes, searched_names


def _sizes(rows: dict[str, dict]) -> dict[str, float]:
    return {name: node["size"] for name, node in rows.items()}


class TestBrowsingDiscoversVideos:
    async def test_each_browsed_video_is_stored_once_and_listed_with_its_disk_size(
        self, execute_gql, init_db,
    ):
        """
        Given the resource tree alpha.mp4 (1000 B), beta.mp4 (2000 B), an empty empty_dir/,
              and drama/ holding charlie.mp4 (3000 B) and delta.mp4 (4000 B)
        When Test-category/Test-resource is browsed twice and drama is browsed once
        Then Test-resource lists exactly alpha (1000), beta (2000) and drama (7000)
        And drama lists exactly charlie (3000) and delta (4000)
        And browsing Test-category lists Test-resource at 10000 bytes
        And exactly four video records exist, one per file
        """
        await browse_nodes(execute_gql, RESOURCE_DIR)
        resource = await browse_nodes(execute_gql, RESOURCE_DIR)
        drama = await browse_nodes(execute_gql, DRAMA_DIR)

        assert _sizes(resource) == {"alpha": 1000, "beta": 2000, "drama": 7000}
        assert _sizes(drama) == {"charlie": 3000, "delta": 4000}
        assert (await browse_nodes(execute_gql, "Test-category"))["Test-resource"]["size"] == 10000
        assert sorted(v.path for v in await VideoModel.find_all().to_list()) == [
            f"{RESOURCE_DIR}/alpha.mp4",
            f"{RESOURCE_DIR}/beta.mp4",
            f"{DRAMA_DIR}/charlie.mp4",
            f"{DRAMA_DIR}/delta.mp4",
        ]

    async def test_search_returns_exactly_the_videos_browsing_has_discovered(
        self, execute_gql, init_db,
    ):
        """
        Given only Test-category/Test-resource has been browsed, not drama
        When all videos are searched
        Then the result is exactly alpha and beta, with a total count of 2
        When drama is browsed and all videos are searched again
        Then the result is exactly alpha, beta, charlie and delta, with a total count of 4
        And searching the title keyword "alpha" returns only alpha
        """
        await browse_nodes(execute_gql, RESOURCE_DIR)

        assert await searched_names(execute_gql) == (["alpha", "beta"], 2)

        await browse_nodes(execute_gql, DRAMA_DIR)

        assert await searched_names(execute_gql) == (["alpha", "beta", "charlie", "delta"], 4)
        assert await searched_names(execute_gql, titleKeyword={"keyWord": "alpha"}) == (["alpha"], 1)
