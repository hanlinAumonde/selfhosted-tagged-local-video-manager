"""
Behaviour specification — the single-video edit panel's series write, and what deleting a
video does to the series it was in.

This panel sends the whole target series: it loads every member after the user picks a
series name, and the user drags the one video being edited into place among them. Where
each video lands is decided by ``SeriesService`` (see ``test_series_assignment.py``); what
is under test here is that ``CatalogService`` routes the edit there, keeps the returned
video consistent with what was stored, and still refuses an ambiguous or overreaching
ordering before anything is written.

One save from this panel must not be able to drag other videos out of the series they
belong to, so every other id in ``orders`` has to be a current member of the target,
``orders`` has to name the video being edited, and it has to be free of duplicate ids and
duplicate order values.
"""

import pytest
from pydantic import ValidationError

from src.errors import InputValidationError
from src.features.catalog.series import SeriesModel
from src.schema.types.pydantic_types.video_type import (
    SeriesFieldInputModel,
    UpdateVideoMetadataInputModel,
)
from tests.series_helpers import series_name_of, stored_series

pytestmark = pytest.mark.unit


class _NoLocks:
    """A lock registry that reports nothing locked; migration is not what is under test."""

    async def locked_paths(self, db_paths) -> set:
        return set()

    async def is_locked(self, db_path: str) -> bool:
        return False


@pytest.fixture
def catalog_svc(catalog_svc_factory):
    return catalog_svc_factory(_NoLocks())


def _edit(video, *, series=None, **kwargs) -> UpdateVideoMetadataInputModel:
    return UpdateVideoMetadataInputModel(
        videoId=str(video.id), tags=kwargs.get("tags", []), series=series,
        name=kwargs.get("name"),
    )


def _ordering(name, *videos) -> SeriesFieldInputModel:
    """A series assignment carrying the panel's list in the order it was dragged into."""
    return SeriesFieldInputModel(
        name=name,
        clear=False,
        orders=[
            {"videoId": str(v.id), "order": i} for i, v in enumerate(videos, start=1)
        ],
    )


async def _videos(video_factory, *names):
    return [await video_factory(name=n) for n in names]


# -----------------------------------------------------------------------
# ------------------- placing the edited video by hand -------------------
# -----------------------------------------------------------------------

async def test_the_edited_video_lands_where_the_panel_placed_it(
    video_factory, series_factory, catalog_svc
):
    # Given series "Show" stored as [a, b, c, d]
    a, b, c, d = await _videos(video_factory, "a", "b", "c", "d")
    await series_factory("Show", a, b, c, d)
    # And video v in no series
    v = await video_factory(name="v")

    # When v is edited with the series ordering a, b, v, c, d under "Show"
    await catalog_svc.update_metadata(_edit(v, series=_ordering("Show", a, b, v, c, d)))

    # Then "Show" is stored as [a, b, v, c, d]
    assert await stored_series("Show") == ["a", "b", "v", "c", "d"]
    # And v references "Show" by seriesId
    assert await series_name_of(v) == "Show"


async def test_moving_the_edited_video_within_its_own_series_reorders_it(
    video_factory, series_factory, catalog_svc
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)

    # When c is edited with the series ordering c, a, b under "Show"
    await catalog_svc.update_metadata(_edit(c, series=_ordering("Show", c, a, b)))

    # Then "Show" is stored as [c, a, b]
    assert await stored_series("Show") == ["c", "a", "b"]


async def test_the_edited_video_leaves_its_old_series(
    video_factory, series_factory, catalog_svc
):
    # Given series "Other" stored as [v1, v2, v3, v4]
    v1, v2, v3, v4 = await _videos(video_factory, "v1", "v2", "v3", "v4")
    await series_factory("Other", v1, v2, v3, v4)
    # And series "Show" stored as [s1]
    s1 = await video_factory(name="s1")
    await series_factory("Show", s1)

    # When v2 is edited with the series ordering s1, v2 under "Show"
    await catalog_svc.update_metadata(_edit(v2, series=_ordering("Show", s1, v2)))

    # Then "Other" is stored as [v1, v3, v4]
    assert await stored_series("Other") == ["v1", "v3", "v4"]
    # And "Show" is stored as [s1, v2]
    assert await stored_series("Show") == ["s1", "v2"]


async def test_the_returned_video_carries_the_series_it_was_placed_in(
    video_factory, series_factory, catalog_svc
):
    # Given series "Show" stored as [a, b]
    a, b = await _videos(video_factory, "a", "b")
    show = await series_factory("Show", a, b)
    # And video v in series "Other"
    v = await video_factory(name="v")
    await series_factory("Other", v)

    # When v is edited with the series ordering a, b, v under "Show"
    returned = await catalog_svc.update_metadata(_edit(v, series=_ordering("Show", a, b, v)))

    # Then the returned video references "Show" by seriesId
    assert returned.seriesId == show.id


async def test_an_edit_to_other_fields_keeps_the_series_membership(
    video_factory, series_factory, catalog_svc
):
    # Given series "Show" stored as [a, b]
    a, b = await _videos(video_factory, "a", "b")
    await series_factory("Show", a, b)

    # When b is edited with a new name and no series change
    await catalog_svc.update_metadata(_edit(b, name="renamed"))

    # Then b still references "Show" by seriesId
    assert await series_name_of(b) == "Show"
    # And "Show" is still stored as [a, b]
    assert await stored_series("Show") == ["a", "renamed"]


async def test_clearing_a_video_out_of_a_series_removes_it_from_the_series(
    video_factory, series_factory, catalog_svc
):
    # Given series "Show" stored as [a, b, c]
    a, b, c = await _videos(video_factory, "a", "b", "c")
    await series_factory("Show", a, b, c)

    # When b is edited with series cleared
    returned = await catalog_svc.update_metadata(
        _edit(b, series=SeriesFieldInputModel(clear=True))
    )

    # Then "Show" is stored as [a, c]
    assert await stored_series("Show") == ["a", "c"]
    # And b references no series
    assert await series_name_of(b) is None
    # And the returned video references no series
    assert returned.seriesId is None


async def test_a_series_left_empty_by_the_edit_is_deleted(
    video_factory, series_factory, catalog_svc
):
    # Given series "Solo" stored as [solo]
    solo = await video_factory(name="solo")
    await series_factory("Solo", solo)
    # And series "Show" stored as [s1]
    s1 = await video_factory(name="s1")
    await series_factory("Show", s1)

    # When solo is edited with the series ordering s1, solo under "Show"
    await catalog_svc.update_metadata(_edit(solo, series=_ordering("Show", s1, solo)))

    # Then no series named "Solo" exists
    assert await stored_series("Solo") is None


# -----------------------------------------------------------------------
# ---------------------------- the input guard ---------------------------
# -----------------------------------------------------------------------

async def test_an_ordering_that_omits_the_edited_video_is_refused(
    video_factory, series_factory, catalog_svc
):
    # Given series "Show" stored as [a, b]
    a, b = await _videos(video_factory, "a", "b")
    await series_factory("Show", a, b)

    # When a is edited with the series ordering b under "Show"
    # Then the edit is refused
    with pytest.raises(InputValidationError):
        await catalog_svc.update_metadata(_edit(a, series=_ordering("Show", b)))

    # And "Show" is still stored as [a, b]
    assert await stored_series("Show") == ["a", "b"]


async def test_an_ordering_naming_a_video_from_another_series_is_refused(
    video_factory, series_factory, catalog_svc
):
    # Given series "Show" stored as [a]
    a = await video_factory(name="a")
    await series_factory("Show", a)
    # And series "Other" stored as [f]
    f = await video_factory(name="f")
    await series_factory("Other", f)

    # When a is edited with the series ordering a, f under "Show"
    # Then the edit is refused
    with pytest.raises(InputValidationError):
        await catalog_svc.update_metadata(_edit(a, series=_ordering("Show", a, f)))

    # And "Other" is still stored as [f]
    assert await stored_series("Other") == ["f"]


async def test_an_ordering_naming_other_videos_under_a_series_that_does_not_exist_is_refused(
    video_factory, catalog_svc
):
    # Given video a in no series
    # And video b in no series
    a, b = await _videos(video_factory, "a", "b")
    # And no series named "New"
    # When a is edited with the series ordering a, b under "New"
    # Then the edit is refused
    with pytest.raises(InputValidationError):
        await catalog_svc.update_metadata(_edit(a, series=_ordering("New", a, b)))

    # And no series named "New" exists
    assert await stored_series("New") is None


async def test_an_ordering_with_a_duplicate_order_value_is_refused(
    video_factory, series_factory, catalog_svc
):
    # Given series "Show" stored as [a, b]
    a, b = await _videos(video_factory, "a", "b")
    await series_factory("Show", a, b)

    # When a is edited with an ordering giving a and b the same order value
    series = SeriesFieldInputModel(
        name="Show",
        clear=False,
        orders=[
            {"videoId": str(a.id), "order": 1},
            {"videoId": str(b.id), "order": 1},
        ],
    )

    # Then the edit is refused
    with pytest.raises(InputValidationError):
        await catalog_svc.update_metadata(_edit(a, series=series))


async def test_an_ordering_with_a_duplicate_video_id_is_refused(
    video_factory, series_factory, catalog_svc
):
    # Given series "Show" stored as [a]
    a = await video_factory(name="a")
    await series_factory("Show", a)

    # When a is edited with an ordering listing a twice
    series = SeriesFieldInputModel(
        name="Show",
        clear=False,
        orders=[
            {"videoId": str(a.id), "order": 1},
            {"videoId": str(a.id), "order": 2},
        ],
    )

    # Then the edit is refused
    with pytest.raises(InputValidationError):
        await catalog_svc.update_metadata(_edit(a, series=series))


def test_an_empty_ordering_is_refused_when_a_series_is_being_assigned():
    # When a series assignment to "Show" is built with no orders
    # Then input validation rejects it
    with pytest.raises(ValidationError):
        SeriesFieldInputModel(name="Show", clear=False, orders=[])


# -----------------------------------------------------------------------
# ---------------------- deleting a video in a series --------------------
# -----------------------------------------------------------------------

async def test_deleting_a_video_removes_it_from_its_series(
    video_factory, series_factory, catalog_svc, local_resource_dir
):
    # Given series "Show" stored as [a, b, c], whose files exist on disk
    a, b, c = await _videos(video_factory, "a", "b", "c")
    for name in ("a", "b", "c"):
        (local_resource_dir / f"{name}.mp4").write_bytes(b"x")
    await series_factory("Show", a, b, c)

    # When b is deleted
    await catalog_svc.delete_video(str(b.id))

    # Then "Show" is stored as [a, c]
    assert await stored_series("Show") == ["a", "c"]


async def test_deleting_the_last_video_of_a_series_deletes_the_series(
    video_factory, series_factory, catalog_svc, local_resource_dir
):
    # Given series "Solo" stored as [s], whose file exists on disk
    s = await video_factory(name="s")
    (local_resource_dir / "s.mp4").write_bytes(b"x")
    await series_factory("Solo", s)

    # When s is deleted
    await catalog_svc.delete_video(str(s.id))

    # Then no series named "Solo" exists
    assert await SeriesModel.find_one({"name": "Solo"}) is None
