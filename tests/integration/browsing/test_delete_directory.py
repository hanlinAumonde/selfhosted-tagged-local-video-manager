"""Delete all on a folder: the videos always go, and what happens to the folder is the
user's choice — kept and listed empty, or removed from the browser (and from storage when
nothing else is left in it). A folder removed from the browser comes back in place when a
new folder of the same name is created.
"""

from tests.integration.graphql_documents import BATCH_DELETE_SUBSCRIPTION, CREATE_DIRECTORY
from tests.integration.helpers import (
    DRAMA_DIR,
    RESOURCE_DIR,
    assert_no_errors,
    browse_nodes,
    discover_videos,
    make_batch_input,
    searched_names,
)


async def _delete_all(subscribe_gql, relative_path: str, strategy: str) -> None:
    events = await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": make_batch_input(
        [], relative_path, directoryDeletion=strategy,
    )})
    for event in events:
        assert_no_errors(event)
    assert events[-1].data["batchDeleteSubscription"]["result"]["resultType"] == "Success"


class TestDeleteAllKeepingTheFolder:
    async def test_folder_stays_listed_and_empty(
        self, execute_gql, subscribe_gql, init_db, integration_resource_dir,
    ):
        """
        Given charlie and delta in drama, discovered by browsing
        When Delete all runs on drama choosing KeepFolder
        Then drama/charlie.mp4 and drama/delta.mp4 are gone but the drama folder remains on disk
        And Test-resource still lists drama, at 0 bytes
        And drama lists nothing
        And searching all videos returns neither charlie nor delta
        """
        await discover_videos(execute_gql, RESOURCE_DIR, DRAMA_DIR)

        await _delete_all(subscribe_gql, DRAMA_DIR, "KeepFolder")

        drama = integration_resource_dir / "drama"
        assert drama.is_dir() and list(drama.iterdir()) == []
        assert (await browse_nodes(execute_gql, RESOURCE_DIR))["drama"]["size"] == 0
        assert await browse_nodes(execute_gql, DRAMA_DIR) == {}
        assert await searched_names(execute_gql) == (["alpha", "beta"], 2)


class TestDeleteAllWithTheFolder:
    async def test_an_emptied_folder_is_removed_from_storage(
        self, execute_gql, subscribe_gql, init_db, integration_resource_dir,
    ):
        """
        Given charlie and delta in drama, discovered by browsing, and nothing else in drama
        When Delete all runs on drama choosing DeleteFolder
        Then the drama folder no longer exists on disk
        And Test-resource lists exactly alpha and beta
        """
        await discover_videos(execute_gql, RESOURCE_DIR, DRAMA_DIR)

        await _delete_all(subscribe_gql, DRAMA_DIR, "DeleteFolder")

        assert not (integration_resource_dir / "drama").exists()
        assert sorted(await browse_nodes(execute_gql, RESOURCE_DIR)) == ["alpha", "beta"]

    async def test_a_folder_still_holding_other_files_is_hidden_but_left_on_disk(
        self, execute_gql, subscribe_gql, init_db, integration_resource_dir,
    ):
        """
        Given charlie and delta in drama, discovered by browsing, and drama/charlie.srt beside them
        When Delete all runs on drama choosing DeleteFolder
        Then the videos are gone, while drama and drama/charlie.srt remain on disk
        And Test-resource lists exactly alpha and beta
        """
        subtitle = integration_resource_dir / "drama" / "charlie.srt"
        subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n")
        await discover_videos(execute_gql, RESOURCE_DIR, DRAMA_DIR)

        await _delete_all(subscribe_gql, DRAMA_DIR, "DeleteFolder")

        assert [p.name for p in (integration_resource_dir / "drama").iterdir()] == ["charlie.srt"]
        assert sorted(await browse_nodes(execute_gql, RESOURCE_DIR)) == ["alpha", "beta"]

    async def test_new_folder_with_the_hidden_folders_name_brings_it_back_in_place(
        self, execute_gql, subscribe_gql, init_db, integration_resource_dir,
    ):
        """
        Given drama hidden by Delete all with DeleteFolder while drama/charlie.srt was left in it
        When a new folder named "drama" is created in Test-resource
        Then the creation succeeds
        And drama/charlie.srt is still on disk, untouched
        And Test-resource lists drama again
        """
        subtitle = integration_resource_dir / "drama" / "charlie.srt"
        subtitle.write_text("subtitle")
        await discover_videos(execute_gql, RESOURCE_DIR, DRAMA_DIR)
        await _delete_all(subscribe_gql, DRAMA_DIR, "DeleteFolder")

        created = await execute_gql(CREATE_DIRECTORY, {"input": {
            "parentPath": {"relativePath": RESOURCE_DIR, "skipCache": False, "recursiveCalculation": True},
            "name": "drama",
        }})

        assert_no_errors(created)
        assert created.data["createDirectory"]["success"] is True
        assert subtitle.read_text() == "subtitle"
        assert sorted(await browse_nodes(execute_gql, RESOURCE_DIR)) == ["alpha", "beta", "drama"]
