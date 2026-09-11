"""Tests for the ``searchInDirectory`` query.

The recursive walk and the matching belong to ``BrowseFileService`` (which is mocked).
What is tested here is the delivery layer's own job: validate the input contract,
delegate, and map the service's entries onto ``FileBrowseNode`` — the same node shape
``browseDirectory`` publishes, so the frontend can render a result set through the table
it already has.
"""

import pytest

from src.features.browsing.browse_file_service import DirectoryEntry, VideoEntry
from tests.graphql.helpers import (
    SEARCH_IN_DIRECTORY,
    assert_error_contains,
    assert_no_errors,
    make_relative_path_input,
    make_search_in_directory_input,
)

pytestmark = pytest.mark.query


async def _entry(video_factory, relative: str, relative_dir: str = "", is_locked: bool = False,
                 **fields) -> VideoEntry:
    document = await video_factory(
        path=f"Test-category/Test-resource/{relative}", **fields
    )
    return VideoEntry(document=document, is_locked=is_locked, relative_dir=relative_dir)


# -----------------------------------------------------------------------
# ------------------- delegation and mapping ------------------------------
# -----------------------------------------------------------------------

async def test_search_in_directory_returns_the_matching_videos_as_browse_nodes(
    execute_gql, mock_browse_file_service, init_db, video_factory,
):
    """
    Given a browse service that reports two matching videos for a directory
    When searchInDirectory is queried for that directory
    Then two nodes come back carrying those videos' ids and names
    """
    first = await _entry(video_factory, "a.mp4", name="Holiday One")
    second = await _entry(video_factory, "b.mp4", name="Holiday Two")
    mock_browse_file_service.search_videos_in_directory.return_value = [first, second]

    result = await execute_gql(
        SEARCH_IN_DIRECTORY, {"input": make_search_in_directory_input(name="holiday")}
    )

    assert_no_errors(result)
    nodes = result.data["searchInDirectory"]
    assert [node["node"]["name"] for node in nodes] == ["Holiday One", "Holiday Two"]
    assert [node["node"]["id"] for node in nodes] == [
        str(first.document.id), str(second.document.id)
    ]


async def test_the_criteria_reach_the_service_unchanged(
    execute_gql, mock_browse_file_service, init_db,
):
    """
    Given a name keyword, an author keyword and two tags in the query input
    When searchInDirectory is queried
    Then the browse service was called with the parsed directory path and exactly those
         three criteria
    """
    await execute_gql(
        SEARCH_IN_DIRECTORY,
        {
            "input": make_search_in_directory_input(
                relative_path="Test-category/Test-resource/season_1",
                name="holiday",
                author="alice",
                tags=["travel", "2024"],
            )
        },
    )

    call = mock_browse_file_service.search_videos_in_directory.await_args
    abs_path, criteria = call.args
    assert abs_path.category == "Test-category"
    assert abs_path.abs_path.endswith("Test-resource/season_1")
    assert criteria.name == "holiday"
    assert criteria.author == "alice"
    assert list(criteria.tags) == ["travel", "2024"]


async def test_a_result_publishes_the_sub_directory_it_was_found_in(
    execute_gql, mock_browse_file_service, init_db, video_factory,
):
    """
    Given a matching video the service reports as living in "season_1"
    When searchInDirectory is queried
    Then its node's relativePath is "season_1"
    """
    mock_browse_file_service.search_videos_in_directory.return_value = [
        await _entry(video_factory, "season_1/ep.mp4", relative_dir="season_1", name="Episode")
    ]

    result = await execute_gql(
        SEARCH_IN_DIRECTORY, {"input": make_search_in_directory_input(name="ep")}
    )

    assert_no_errors(result)
    assert result.data["searchInDirectory"][0]["node"]["relativePath"] == "season_1"


async def test_a_locked_result_is_published_as_locked(
    execute_gql, mock_browse_file_service, init_db, video_factory,
):
    """
    Given a matching video the service flags as held by an unfinished task
    When searchInDirectory is queried
    Then its node's isLocked is true
    """
    mock_browse_file_service.search_videos_in_directory.return_value = [
        await _entry(video_factory, "held.mp4", is_locked=True, name="Held")
    ]

    result = await execute_gql(
        SEARCH_IN_DIRECTORY, {"input": make_search_in_directory_input(name="held")}
    )

    assert_no_errors(result)
    assert result.data["searchInDirectory"][0]["node"]["isLocked"] is True


async def test_no_match_returns_an_empty_list_rather_than_an_error(
    execute_gql, mock_browse_file_service, init_db,
):
    """
    Given a browse service that reports no match
    When searchInDirectory is queried
    Then an empty list comes back
    """
    mock_browse_file_service.search_videos_in_directory.return_value = []

    result = await execute_gql(
        SEARCH_IN_DIRECTORY, {"input": make_search_in_directory_input(name="nothing")}
    )

    assert_no_errors(result)
    assert result.data["searchInDirectory"] == []


# -----------------------------------------------------------------------
# ------------------- input contract --------------------------------------
# -----------------------------------------------------------------------

async def test_an_unparseable_directory_path_is_refused_before_the_service_is_called(
    execute_gql, mock_browse_file_service, init_db,
):
    """
    Given a relative path naming a category that is not configured
    When searchInDirectory is queried
    Then an input validation error comes back
      And the browse service was never called
    """
    result = await execute_gql(
        SEARCH_IN_DIRECTORY,
        {"input": make_search_in_directory_input(relative_path="not-a-category", name="x")},
    )

    assert_error_contains(result, "SearchInDirectoryInput")
    mock_browse_file_service.search_videos_in_directory.assert_not_awaited()


async def test_regex_metacharacters_in_a_keyword_are_escaped_by_the_input_model(
    execute_gql, mock_browse_file_service, init_db,
):
    """
    Given a name keyword containing regex metacharacters
    When searchInDirectory is queried
    Then the keyword the service receives has them escaped, exactly as the search page's
         keywords are
    """
    await execute_gql(
        SEARCH_IN_DIRECTORY, {"input": make_search_in_directory_input(name="a.b")}
    )

    _, criteria = mock_browse_file_service.search_videos_in_directory.await_args.args
    assert criteria.name == r"a\.b"


async def test_a_keyword_longer_than_the_configured_limit_is_refused(
    execute_gql, mock_browse_file_service, init_db, test_settings,
):
    """
    Given a name keyword longer than validation.name_max_length
    When searchInDirectory is queried
    Then an input validation error comes back
    """
    too_long = "a" * (test_settings.validation.name_max_length + 1)

    result = await execute_gql(
        SEARCH_IN_DIRECTORY, {"input": make_search_in_directory_input(name=too_long)}
    )

    assert_error_contains(result, "SearchInDirectoryInput")
    mock_browse_file_service.search_videos_in_directory.assert_not_awaited()


async def test_more_tags_than_the_configured_limit_are_refused(
    execute_gql, mock_browse_file_service, init_db, test_settings,
):
    """
    Given more tags than validation.max_tags_count
    When searchInDirectory is queried
    Then an input validation error comes back
    """
    too_many = [f"tag-{index}" for index in range(test_settings.validation.max_tags_count + 1)]

    result = await execute_gql(
        SEARCH_IN_DIRECTORY, {"input": make_search_in_directory_input(tags=too_many)}
    )

    assert_error_contains(result, "SearchInDirectoryInput")
    mock_browse_file_service.search_videos_in_directory.assert_not_awaited()


# -----------------------------------------------------------------------
# ------------------- browseDirectory is unaffected ------------------------
# -----------------------------------------------------------------------

async def test_browse_directory_nodes_still_publish_no_relative_path(
    execute_gql, mock_browse_file_service, init_db, video_factory,
):
    """
    Given an ordinary directory listing
    When browseDirectory is queried
    Then every node's relativePath is null — the field exists for search results, and a
         listing's rows are all in the directory being listed
    """
    document = await video_factory(path="Test-category/Test-resource/a.mp4", name="A")
    mock_browse_file_service.get_node_list_in_directory.return_value = [
        DirectoryEntry(name="subdir", size=10.0, last_modify_time=1.0),
        VideoEntry(document=document, is_locked=False),
    ]

    result = await execute_gql(
        """
        query BrowseDirectory($input: RelativePathInput!) {
          browseDirectory(input: $input) { node { name relativePath } }
        }
        """,
        {"input": make_relative_path_input("Test-category/Test-resource")},
    )

    assert_no_errors(result)
    assert [node["node"]["relativePath"] for node in result.data["browseDirectory"]] == [
        None, None
    ]
