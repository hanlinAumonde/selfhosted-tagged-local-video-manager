"""
Searching video files inside a browsed directory.

Two concerns live here:

1. ``get_all_video_entries_in_directory`` takes a *search operator* — a predicate
   consulted for every video file met during the recursive walk.
2. ``search_videos_in_directory`` builds on it: it matches catalogued videos against
   name / author / tag criteria and returns them as browse rows.
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.errors import InputValidationError
from src.features.browsing.browse_file_service import DirectorySearchCriteria, VideoEntry
from src.features.catalog.video import VideoModel
from src.platform.storage.absolute_path import AbsolutePath

pytestmark = pytest.mark.unit


def _abs_path(local_resource_handler_service, fs_path: Path | str) -> AbsolutePath:
    """An AbsolutePath for a real directory inside the on-disk fixture tree."""
    return AbsolutePath.from_existing_path(
        path=str(fs_path).replace("\\", "/"),
        category="Test-category",
        handler=local_resource_handler_service.get_handler("Test-category"),
    )


async def _catalogue(video_factory, local_resource_dir: Path, relative: str, **fields) -> VideoModel:
    """Put a video file on disk under the fixture tree and give it a document."""
    file_path = local_resource_dir / relative
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"x" * 10)
    return await video_factory(
        path=f"Test-category/Test-resource/{relative.replace(chr(92), '/')}", **fields
    )


def _names(entries: list[VideoEntry]) -> list[str]:
    return sorted(entry.document.name for entry in entries)


# -----------------------------------------------------------------------
# ------------------- search operator on the recursive walk ---------------
# -----------------------------------------------------------------------

def test_walk_without_operator_returns_every_video_as_before(
    browse_svc, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a directory tree holding video files in itself and in its sub-directories
    When get_all_video_entries_in_directory is called with no search operator
    Then every video file under the tree is returned, exactly as it was before the
         operator parameter existed
    """
    root_fs = str(local_resource_dir).replace("\\", "/")

    entries = browse_svc.get_all_video_entries_in_directory(root_fs, "Test-category")

    assert sorted(e.name for e in entries) == ["movie_a.mp4", "movie_b.mp4", "movie_c.mp4"]


def test_operator_returning_false_excludes_the_entry(
    browse_svc, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a directory tree holding several video files
    When the walk runs with an operator that accepts only one particular file name
    Then only that file is returned
    """
    root_fs = str(local_resource_dir).replace("\\", "/")

    entries = browse_svc.get_all_video_entries_in_directory(
        root_fs, "Test-category", search_operator=lambda entry: entry.name == "movie_b.mp4",
    )

    assert [e.name for e in entries] == ["movie_b.mp4"]


def test_operator_returning_none_keeps_the_entry(
    browse_svc, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a directory tree holding video files
    When the walk runs with an operator that returns None for every entry
    Then every video file is returned, because only an explicit refusal excludes one
    """
    root_fs = str(local_resource_dir).replace("\\", "/")

    entries = browse_svc.get_all_video_entries_in_directory(
        root_fs, "Test-category", search_operator=lambda entry: None,
    )

    assert sorted(e.name for e in entries) == ["movie_a.mp4", "movie_b.mp4", "movie_c.mp4"]


def test_a_rejected_entry_does_not_stop_the_recursion(
    browse_svc, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a directory whose own video files are all rejected by the operator
      and whose sub-directory holds a video file the operator accepts
    When the walk runs
    Then the accepted file from the sub-directory is returned
    """
    root_fs = str(local_resource_dir).replace("\\", "/")

    entries = browse_svc.get_all_video_entries_in_directory(
        root_fs, "Test-category", search_operator=lambda entry: entry.name == "movie_c.mp4",
    )

    assert [e.name for e in entries] == ["movie_c.mp4"]


def test_operator_is_consulted_for_video_files_only(
    browse_svc, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a directory tree holding sub-directories, a video file and a non-video file
    When the walk runs with a recording operator
    Then the operator was asked about the video file only — never about a directory,
         never about a file that is not a video
    """
    root_fs = str(local_resource_dir).replace("\\", "/")
    asked: list[str] = []

    def record(entry):
        asked.append(entry.name)
        return True

    browse_svc.get_all_video_entries_in_directory(
        root_fs, "Test-category", search_operator=record,
    )

    assert sorted(asked) == ["movie_a.mp4", "movie_b.mp4", "movie_c.mp4"]


# -----------------------------------------------------------------------
# ------------------- search_videos_in_directory: matching ----------------
# -----------------------------------------------------------------------

async def test_name_keyword_matches_case_insensitively_as_a_substring(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a catalogued video whose name is "Holiday Trip"
    When the directory is searched with the name keyword "holiday"
    Then that video is in the results
    """
    await _catalogue(video_factory, local_resource_dir, "holiday.mp4", name="Holiday Trip")
    await _catalogue(video_factory, local_resource_dir, "other.mp4", name="Something Else")

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday"),
    )

    assert _names(results) == ["Holiday Trip"]


async def test_name_keyword_matches_the_catalogued_name_not_the_file_name(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a video file "clip_01.mp4" whose document was renamed to "Holiday Trip"
    When the directory is searched with the name keyword "holiday"
    Then that video is in the results
      And searching for "clip_01" returns nothing, because the catalogued name is what a
          user sees and therefore what they search
    """
    await _catalogue(video_factory, local_resource_dir, "clip_01.mp4", name="Holiday Trip")
    abs_path = _abs_path(local_resource_handler_service, local_resource_dir)

    by_catalogued_name = await browse_svc.search_videos_in_directory(
        abs_path, DirectorySearchCriteria(name="holiday")
    )
    by_file_name = await browse_svc.search_videos_in_directory(
        abs_path, DirectorySearchCriteria(name="clip_01")
    )

    assert _names(by_catalogued_name) == ["Holiday Trip"]
    assert by_file_name == []


async def test_author_keyword_matches_case_insensitively_as_a_substring(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a catalogued video whose author is "Alice Smith"
    When the directory is searched with the author keyword "alice"
    Then that video is in the results
    """
    await _catalogue(video_factory, local_resource_dir, "one.mp4", name="One", author="Alice Smith")
    await _catalogue(video_factory, local_resource_dir, "two.mp4", name="Two", author="Bob Jones")

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(author="alice"),
    )

    assert _names(results) == ["One"]


async def test_tags_must_all_be_present(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given one video tagged ["travel", "2024"] and another tagged ["travel"]
    When the directory is searched with tags ["travel", "2024"]
    Then only the first video is in the results
    """
    await _catalogue(
        video_factory, local_resource_dir, "both.mp4", name="Both", tags=["travel", "2024"]
    )
    await _catalogue(video_factory, local_resource_dir, "one.mp4", name="One", tags=["travel"])

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(tags=["travel", "2024"]),
    )

    assert _names(results) == ["Both"]


async def test_criteria_from_different_fields_are_combined_with_and(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given one video named "Holiday" by author "Alice"
      and another named "Holiday" by author "Bob"
    When the directory is searched with name "holiday" and author "alice"
    Then only the first video is in the results
    """
    await _catalogue(
        video_factory, local_resource_dir, "a.mp4", name="Holiday", author="Alice"
    )
    await _catalogue(
        video_factory, local_resource_dir, "b.mp4", name="Holiday", author="Bob"
    )

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday", author="alice"),
    )

    assert len(results) == 1
    assert results[0].document.author == "Alice"


async def test_a_blank_field_is_ignored_rather_than_matched_against(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given several catalogued videos by different authors
    When the directory is searched with only a name keyword, the author left blank
    Then the author is not used as a filter and every name match is returned
    """
    await _catalogue(
        video_factory, local_resource_dir, "a.mp4", name="Holiday One", author="Alice"
    )
    await _catalogue(
        video_factory, local_resource_dir, "b.mp4", name="Holiday Two", author="Bob"
    )

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday", author="", tags=[]),
    )

    assert _names(results) == ["Holiday One", "Holiday Two"]


async def test_a_keyword_is_used_as_the_already_escaped_regex_it_arrives_as(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a catalogued video named "a.b" and another named "axb"
    When the directory is searched with the name keyword the input model produced for
        "a.b" — that is, with the dot escaped
    Then only "a.b" is in the results

    Escaping belongs to ``SearchKeywordModel``, exactly as it does for the search page;
    this service, like ``CatalogService.search_videos``, receives a regex and trusts it.
    """
    await _catalogue(video_factory, local_resource_dir, "dot.mp4", name="a.b")
    await _catalogue(video_factory, local_resource_dir, "nodot.mp4", name="axb")

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name=r"a\.b"),
    )

    assert _names(results) == ["a.b"]


# -----------------------------------------------------------------------
# ------------------- search_videos_in_directory: scope -------------------
# -----------------------------------------------------------------------

async def test_the_search_descends_into_sub_directories(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a matching video sitting two levels below the searched directory
    When the directory is searched
    Then that video is in the results
    """
    await _catalogue(
        video_factory, local_resource_dir, "subdir/deep/buried.mp4", name="Holiday Deep"
    )

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday"),
    )

    assert _names(results) == ["Holiday Deep"]


async def test_a_matching_video_outside_the_searched_directory_is_not_returned(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given two sibling directories, each holding a video matching the criteria
    When one of them is searched
    Then only its own video is in the results — a sibling's path shares no prefix with it
    """
    await _catalogue(video_factory, local_resource_dir, "left/in.mp4", name="Holiday Left")
    await _catalogue(video_factory, local_resource_dir, "right/out.mp4", name="Holiday Right")

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir / "left"),
        DirectorySearchCriteria(name="holiday"),
    )

    assert _names(results) == ["Holiday Left"]


async def test_a_document_whose_file_no_longer_exists_is_not_returned(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a catalogued video matching the criteria whose file was removed from disk
    When the directory is searched
    Then it is not in the results — walking the storage is what decides existence
    """
    await video_factory(
        path="Test-category/Test-resource/vanished.mp4", name="Holiday Vanished"
    )

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday"),
    )

    assert results == []


async def test_a_video_file_with_no_document_is_neither_returned_nor_inserted(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a video file on disk in a directory that has never been browsed, so it has no
        document, whose file name would match the name keyword
    When the directory is searched
    Then it is not in the results
      And no document was inserted for it — searching reads the catalogue, it does not
          extend it
    """
    (local_resource_dir / "holiday_orphan.mp4").write_bytes(b"x" * 10)

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday"),
    )

    assert results == []
    assert await VideoModel.find({}).count() == 0


async def test_only_video_files_are_returned_never_directories(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a sub-directory whose name matches the name keyword
    When the directory is searched
    Then the results hold video files only
    """
    (local_resource_dir / "holiday").mkdir()
    await _catalogue(video_factory, local_resource_dir, "clip.mp4", name="Holiday Clip")

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday"),
    )

    assert all(isinstance(entry, VideoEntry) for entry in results)
    assert _names(results) == ["Holiday Clip"]


# -----------------------------------------------------------------------
# ------------------- search_videos_in_directory: result shape ------------
# -----------------------------------------------------------------------

async def test_a_result_carries_the_sub_directory_it_was_found_in(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a matching video at "<searched>/season_1/ep_2.mp4"
    When the directory is searched
    Then its entry reports "season_1" as the directory it lives in, relative to the
         searched directory, so the browser can tell two same-named results apart
    """
    await _catalogue(
        video_factory, local_resource_dir, "season_1/ep_2.mp4", name="Holiday Episode"
    )

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday"),
    )

    assert [entry.relative_dir for entry in results] == ["season_1"]


async def test_a_result_directly_in_the_searched_directory_reports_no_sub_directory(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a matching video directly inside the searched directory
    When the directory is searched
    Then its entry reports an empty relative directory
    """
    await _catalogue(video_factory, local_resource_dir, "clip.mp4", name="Holiday Clip")

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday"),
    )

    assert [entry.relative_dir for entry in results] == [""]


async def test_a_result_held_by_an_unfinished_task_is_flagged_locked(
    browse_svc, init_db, video_factory, task_factory,
    local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a matching video whose path an active migration task holds
    When the directory is searched
    Then its entry is flagged as locked, so every action on it is refused downstream
    """
    await _catalogue(video_factory, local_resource_dir, "held.mp4", name="Holiday Held")
    await _catalogue(video_factory, local_resource_dir, "free.mp4", name="Holiday Free")
    await task_factory(source_path="Test-category/Test-resource/held.mp4")

    results = await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday"),
    )

    locked = {entry.document.name: entry.is_locked for entry in results}
    assert locked == {"Holiday Held": True, "Holiday Free": False}


async def test_lock_state_is_resolved_once_for_the_whole_result_set(
    browse_svc, init_db, video_factory, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given several matching videos
    When the directory is searched
    Then the path-lock registry was consulted a single time, not once per result
    """
    for index in range(3):
        await _catalogue(
            video_factory, local_resource_dir, f"clip_{index}.mp4", name=f"Holiday {index}"
        )
    spy = AsyncMock(return_value=set())
    browse_svc.pathLocks.locked_paths = spy

    await browse_svc.search_videos_in_directory(
        _abs_path(local_resource_handler_service, local_resource_dir),
        DirectorySearchCriteria(name="holiday"),
    )

    spy.assert_awaited_once()


# -----------------------------------------------------------------------
# ------------------- search_videos_in_directory: refusals ----------------
# -----------------------------------------------------------------------

async def test_a_search_with_no_criteria_at_all_is_refused(
    browse_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
):
    """
    Given a directory to search
    When it is searched with every field blank
    Then an InputValidationError is raised — an unfiltered search is the directory walk
         that browsing already does, and would recurse the whole tree for nothing
    """
    with pytest.raises(InputValidationError):
        await browse_svc.search_videos_in_directory(
            _abs_path(local_resource_handler_service, local_resource_dir),
            DirectorySearchCriteria(name="   ", author=None, tags=[]),
        )


async def test_searching_the_root_level_is_refused(browse_svc, init_db):
    """
    Given the root level, which lists categories rather than a place on the storage
    When it is searched
    Then an InputValidationError is raised
    """
    with pytest.raises(InputValidationError):
        await browse_svc.search_videos_in_directory(
            AbsolutePath(abs_path=None, category=None, handler=None),
            DirectorySearchCriteria(name="holiday"),
        )


async def test_searching_the_category_level_is_refused(
    browse_svc, init_db, local_resource_handler_service,
):
    """
    Given a category level, which lists configured mount points rather than a place on
        the storage
    When it is searched
    Then an InputValidationError is raised
    """
    category_level = AbsolutePath.from_existing_path(
        path="Test-category",
        category="Test-category",
        handler=local_resource_handler_service.get_handler("Test-category"),
    )
    with pytest.raises(InputValidationError):
        await browse_svc.search_videos_in_directory(
            category_level, DirectorySearchCriteria(name="holiday")
        )
