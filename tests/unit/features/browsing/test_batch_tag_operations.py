"""
Behaviour specification — adding and removing tags in one batch request.

A batch tag edit used to be one direction at a time: ``append`` said whether the
supplied list was being added or taken away, so "give these twelve videos the tag
`4k` and take `todo` off them" was two passes over the same documents, each with its
own confirmation and its own chance of ending half-done.

The input now carries both lists, and one pass resolves them:
``new_tags = (old_tags | add) - remove``. The two lists must be disjoint — a tag named
in both says nothing about what the caller wants, so the input contract rejects it
rather than picking a winner.

Every scenario below runs over a *selection* of videos rather than a single one. That
is the capability under test: the videos in one batch do not start from the same tags,
so the interesting claims are all about a mixed selection — which rows change, which
are left alone, and what the tag counts add up to across the whole set.
"""

from pathlib import Path

import pytest

from src.features.browsing.batch_operation_service import BatchResultType
from src.features.catalog.video import VideoModel
from src.features.catalog.video_tag import VideoTagModel
from src.schema.types.pydantic_types.batch_operation_type import (
    TagsOperationMappingInputModel,
)
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit

CATEGORY = "Test-category"


async def _collect(gen) -> list:
    """Drain an async generator into a list."""
    return [item async for item in gen]


def _tags_op(add: list[str] | None = None, remove: list[str] | None = None):
    return TagsOperationMappingInputModel(
        addTags=add or [], removeTags=remove or []
    )


async def _update_by_ids(batch_svc, videos, tags_operation):
    """Run one batch update over a whole selection, by ID."""
    return await _collect(
        batch_svc.batch_update(
            category=CATEGORY,
            videoIDs=[str(v.id) for v in videos],
            fileEntries=None,
            author=None,
            tagsOperation=tags_operation,
        )
    )


async def _tags_of(video: VideoModel) -> set[str]:
    refreshed = await VideoModel.get(video.id)
    return set(refreshed.tags or [])


async def _tag_count(name: str) -> int:
    """The reference count for a tag; zero once the tag record is gone."""
    doc = await VideoTagModel.find_one({"name": name})
    return doc.tag_count if doc is not None else 0


def _write_events(events: list) -> list:
    """The events reporting an actual bulk write, one per pass over the database."""
    return [
        e for e in events
        if e.status and e.status.startswith("Executed batch update operations")
    ]


def _entries(handler_svc: ResourceHandlerService, *fs_paths: Path) -> list:
    handler = handler_svc.get_handler(CATEGORY)
    return [handler.get_entry(str(p).replace("\\", "/")) for p in fs_paths]


# -----------------------------------------------------------------------
# ------------------ Both directions in one request ----------------------
# -----------------------------------------------------------------------

async def test_one_request_adds_and_removes_tags_across_the_whole_selection(
    batch_svc, init_db, video_factory, fs_settings,
):
    a = await video_factory(name="a", tags=["todo"])
    b = await video_factory(name="b", tags=["todo", "raw"])
    c = await video_factory(name="c", tags=["raw"])

    await _update_by_ids(batch_svc, [a, b, c], _tags_op(add=["4k"], remove=["todo"]))

    assert await _tags_of(a) == {"4k"}
    assert await _tags_of(b) == {"raw", "4k"}
    assert await _tags_of(c) == {"raw", "4k"}


async def test_adding_alone_leaves_every_selected_video_s_existing_tags_in_place(
    batch_svc, init_db, video_factory, fs_settings,
):
    a = await video_factory(name="a", tags=["raw"])
    b = await video_factory(name="b", tags=["todo"])
    c = await video_factory(name="c", tags=[])

    await _update_by_ids(batch_svc, [a, b, c], _tags_op(add=["4k"]))

    assert await _tags_of(a) == {"raw", "4k"}
    assert await _tags_of(b) == {"todo", "4k"}
    assert await _tags_of(c) == {"4k"}


async def test_removing_alone_takes_only_the_named_tags_off_the_selection(
    batch_svc, init_db, video_factory, fs_settings,
):
    a = await video_factory(name="a", tags=["raw", "todo"])
    b = await video_factory(name="b", tags=["todo"])
    c = await video_factory(name="c", tags=["raw"])

    await _update_by_ids(batch_svc, [a, b, c], _tags_op(remove=["todo"]))

    assert await _tags_of(a) == {"raw"}
    assert await _tags_of(b) == set()
    assert await _tags_of(c) == {"raw"}


async def test_videos_in_the_selection_that_the_change_does_not_reach_are_left_alone(
    batch_svc, init_db, video_factory, fs_settings,
):
    carries = await video_factory(name="a", tags=["todo", "raw"])
    untouched_one = await video_factory(name="b", tags=["raw"])
    untouched_two = await video_factory(name="c", tags=[])

    events = await _update_by_ids(
        batch_svc,
        [carries, untouched_one, untouched_two],
        _tags_op(remove=["todo"]),
    )

    assert await _tags_of(carries) == {"raw"}
    assert await _tags_of(untouched_one) == {"raw"}
    assert await _tags_of(untouched_two) == set()
    # Only the one video that actually carried the tag is written to.
    assert _write_events(events)[0].status.startswith(
        "Executed batch update operations: 1 modified"
    )


async def test_a_mixed_selection_converges_on_the_same_result_regardless_of_start(
    batch_svc, init_db, video_factory, fs_settings,
):
    already_4k = await video_factory(name="a", tags=["4k", "todo"])
    neither = await video_factory(name="b", tags=[])
    only_todo = await video_factory(name="c", tags=["todo"])

    await _update_by_ids(
        batch_svc, [already_4k, neither, only_todo], _tags_op(add=["4k"], remove=["todo"])
    )

    for video in (already_4k, neither, only_todo):
        tags = await _tags_of(video)
        assert "4k" in tags
        assert "todo" not in tags


async def test_the_selection_is_updated_in_a_single_bulk_write(
    batch_svc, init_db, video_factory, fs_settings,
):
    a = await video_factory(name="a", tags=["todo"])
    b = await video_factory(name="b", tags=["todo"])
    c = await video_factory(name="c", tags=["todo"])

    events = await _update_by_ids(
        batch_svc, [a, b, c], _tags_op(add=["4k"], remove=["todo"])
    )

    writes = _write_events(events)
    assert len(writes) == 1
    assert writes[0].status.startswith("Executed batch update operations: 3 modified")


# -----------------------------------------------------------------------
# -------------------------- Tag reference counts ------------------------
# -----------------------------------------------------------------------

async def test_tag_counts_rise_for_added_tags_and_fall_for_removed_ones(
    batch_svc, init_db, video_factory, tag_factory, fs_settings,
):
    await tag_factory(name="todo", tag_count=2)
    a = await video_factory(name="a", tags=["todo"])
    b = await video_factory(name="b", tags=["todo"])
    c = await video_factory(name="c", tags=["raw"])

    await _update_by_ids(batch_svc, [a, b, c], _tags_op(add=["4k"], remove=["todo"]))

    assert await _tag_count("4k") == 3
    assert await _tag_count("todo") == 0


async def test_a_tag_count_moves_once_per_video_the_change_actually_reaches(
    batch_svc, init_db, video_factory, tag_factory, fs_settings,
):
    await tag_factory(name="todo", tag_count=5)
    a = await video_factory(name="a", tags=["todo"])
    b = await video_factory(name="b", tags=["todo"])
    c = await video_factory(name="c", tags=[])

    await _update_by_ids(batch_svc, [a, b, c], _tags_op(remove=["todo"]))

    assert await _tag_count("todo") == 3


async def test_adding_a_tag_some_of_the_selection_already_carries_counts_only_the_rest(
    batch_svc, init_db, video_factory, tag_factory, fs_settings,
):
    await tag_factory(name="4k", tag_count=1)
    already = await video_factory(name="a", tags=["4k"])
    b = await video_factory(name="b", tags=[])
    c = await video_factory(name="c", tags=["raw"])

    await _update_by_ids(batch_svc, [already, b, c], _tags_op(add=["4k"]))

    assert await _tag_count("4k") == 3


# -----------------------------------------------------------------------
# ------------------ Videos the database has not seen --------------------
# -----------------------------------------------------------------------

async def test_newly_discovered_videos_are_inserted_with_the_added_tags_only(
    batch_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
    fs_settings,
):
    entries = _entries(
        local_resource_handler_service,
        local_resource_dir / "movie_a.mp4",
        local_resource_dir / "movie_b.mp4",
    )

    await _collect(
        batch_svc.batch_update(
            category=CATEGORY,
            videoIDs=None,
            fileEntries=entries,
            author=None,
            tagsOperation=_tags_op(add=["4k"], remove=["todo"]),
        )
    )

    inserted = await VideoModel.find({"category": CATEGORY}).to_list()
    assert len(inserted) == 2
    assert all(set(v.tags) == {"4k"} for v in inserted)


async def test_newly_discovered_videos_are_inserted_untagged_when_nothing_is_added(
    batch_svc, init_db, local_resource_handler_service, local_resource_dir: Path,
    fs_settings,
):
    entries = _entries(
        local_resource_handler_service,
        local_resource_dir / "movie_a.mp4",
        local_resource_dir / "movie_b.mp4",
    )

    await _collect(
        batch_svc.batch_update(
            category=CATEGORY,
            videoIDs=None,
            fileEntries=entries,
            author=None,
            tagsOperation=_tags_op(remove=["todo"]),
        )
    )

    inserted = await VideoModel.find({"category": CATEGORY}).to_list()
    assert len(inserted) == 2
    assert all(not v.tags for v in inserted)


async def test_a_directory_of_known_and_unknown_videos_is_settled_in_one_pass(
    batch_svc, init_db, video_factory, local_resource_handler_service,
    local_resource_dir: Path, fs_settings,
):
    handler = local_resource_handler_service.get_handler(CATEGORY)
    known_paths = [
        handler.convert_to_DB_format_path(
            str(local_resource_dir / name).replace("\\", "/")
        )
        for name in ("movie_a.mp4", "movie_b.mp4")
    ]
    for path in known_paths:
        await video_factory(name=Path(path).stem, path=path, tags=["todo"])

    entries = _entries(
        local_resource_handler_service,
        local_resource_dir / "movie_a.mp4",
        local_resource_dir / "movie_b.mp4",
        local_resource_dir / "subdir" / "movie_c.mp4",
    )

    events = await _collect(
        batch_svc.batch_update(
            category=CATEGORY,
            videoIDs=None,
            fileEntries=entries,
            author=None,
            tagsOperation=_tags_op(add=["4k"], remove=["todo"]),
        )
    )

    all_videos = await VideoModel.find({"category": CATEGORY}).to_list()
    assert len(all_videos) == 3
    assert all(set(v.tags) == {"4k"} for v in all_videos)
    assert len(_write_events(events)) == 1


# -----------------------------------------------------------------------
# ---------------------------- Nothing to do -----------------------------
# -----------------------------------------------------------------------

async def test_the_operation_reports_already_up_to_date_when_no_video_changes(
    batch_svc, init_db, video_factory, fs_settings,
):
    a = await video_factory(name="a", tags=["4k"])
    b = await video_factory(name="b", tags=["4k"])
    c = await video_factory(name="c", tags=["4k"])

    events = await _update_by_ids(
        batch_svc, [a, b, c], _tags_op(add=["4k"], remove=["todo"])
    )

    assert events[-1].result_type == BatchResultType.AlreadyUpToDate


async def test_a_selection_where_only_some_videos_change_still_reports_success(
    batch_svc, init_db, video_factory, fs_settings,
):
    changes = await video_factory(name="a", tags=["todo"])
    settled_one = await video_factory(name="b", tags=["4k"])
    settled_two = await video_factory(name="c", tags=["4k"])

    events = await _update_by_ids(
        batch_svc,
        [changes, settled_one, settled_two],
        _tags_op(add=["4k"], remove=["todo"]),
    )

    assert events[-1].result_type == BatchResultType.Success
