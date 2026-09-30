"""
Behaviour specification — the one-off move of stored series data into its own collection.

Before this change a series was two fields on each video, ``seriesName`` and
``seriesOrder``. The script turns every distinct ``seriesName`` into a series document
whose ``videoIds`` list the members in the order they used to read, points each member at
it through ``seriesId``, and removes the old fields.

"The order they used to read" is the order the old code showed: numbered members first by
number, members with no number after them, ties broken by video name. Numbers that had
drifted (gaps, duplicates) are not carried over — only the sequence is.

The script must be safe to run twice: a database that has already been migrated is left
as it is.
"""

import pymongo
import pytest

from scripts.migrate_series_to_collection import migrate_series
from src.features.catalog.series import SeriesModel
from src.features.catalog.video import VideoModel
from tests.series_helpers import series_name_of, stored_series

pytestmark = pytest.mark.unit


def _videos_collection():
    return VideoModel.get_pymongo_collection()


async def _legacy(video_factory, name, series=None, order=None) -> VideoModel:
    """A video stored the way the old code stored it: series name and number on the video."""
    video = await video_factory(name=name)
    legacy_fields = {"seriesName": series, "seriesOrder": order}
    await _videos_collection().update_one({"_id": video.id}, {"$set": legacy_fields})
    return video


async def _run():
    await migrate_series(_videos_collection().database)


async def test_each_distinct_series_name_becomes_one_series_document(video_factory):
    # Given videos a, b carrying seriesName "Show"
    await _legacy(video_factory, "a", "Show", 1)
    await _legacy(video_factory, "b", "Show", 2)
    # And video x carrying seriesName "Other"
    await _legacy(video_factory, "x", "Other", 1)
    # And video n carrying no seriesName
    await _legacy(video_factory, "n")

    # When the migration runs
    await _run()

    # Then exactly two series exist, named "Show" and "Other"
    names = sorted(s.name for s in await SeriesModel.find_all().to_list())
    assert names == ["Other", "Show"]


async def test_members_are_listed_in_the_order_their_old_numbers_gave(video_factory):
    # Given videos carrying seriesName "Show": c with order 3, a with order 1, b with order 2
    await _legacy(video_factory, "c", "Show", 3)
    await _legacy(video_factory, "a", "Show", 1)
    await _legacy(video_factory, "b", "Show", 2)

    # When the migration runs
    await _run()

    # Then "Show" is stored as [a, b, c]
    assert await stored_series("Show") == ["a", "b", "c"]


async def test_members_with_no_old_number_are_listed_after_the_numbered_ones(video_factory):
    # Given videos carrying seriesName "Show": loose with no order, a with order 1, b with order 2
    await _legacy(video_factory, "loose", "Show", None)
    await _legacy(video_factory, "a", "Show", 1)
    await _legacy(video_factory, "b", "Show", 2)

    # When the migration runs
    await _run()

    # Then "Show" is stored as [a, b, loose]
    assert await stored_series("Show") == ["a", "b", "loose"]


async def test_members_sharing_an_old_number_are_ordered_by_name(video_factory):
    # Given videos carrying seriesName "Show": "zeta" with order 1, "alpha" with order 1, "mid" with order 2
    await _legacy(video_factory, "zeta", "Show", 1)
    await _legacy(video_factory, "alpha", "Show", 1)
    await _legacy(video_factory, "mid", "Show", 2)

    # When the migration runs
    await _run()

    # Then "Show" is stored as [alpha, zeta, mid]
    assert await stored_series("Show") == ["alpha", "zeta", "mid"]


async def test_every_member_references_its_new_series_and_loses_the_old_fields(video_factory):
    # Given videos a, b carrying seriesName "Show" with orders 1 and 2
    a = await _legacy(video_factory, "a", "Show", 1)
    b = await _legacy(video_factory, "b", "Show", 2)
    # And video n carrying no seriesName
    n = await _legacy(video_factory, "n")

    # When the migration runs
    await _run()

    # Then a and b reference "Show" by seriesId
    assert await series_name_of(a) == "Show"
    assert await series_name_of(b) == "Show"
    # And no video document has a seriesName or seriesOrder field
    leftover = await _videos_collection().count_documents({
        "$or": [{"seriesName": {"$exists": True}}, {"seriesOrder": {"$exists": True}}]
    })
    assert leftover == 0
    # And n references no series
    assert await series_name_of(n) is None


async def test_the_old_series_index_is_dropped(init_db):
    # Given the videos collection has the index seriesName_1_seriesOrder_1
    await _videos_collection().create_index(
        [("seriesName", pymongo.ASCENDING), ("seriesOrder", pymongo.ASCENDING)]
    )

    # When the migration runs
    await _run()

    # Then the videos collection no longer has that index
    indexes = await _videos_collection().index_information()
    assert "seriesName_1_seriesOrder_1" not in indexes


async def test_a_run_interrupted_after_creating_the_series_is_completed_by_the_next_run(
    video_factory,
):
    # Given videos a, b, c carrying seriesName "Show" with orders 1, 2 and 3
    a = await _legacy(video_factory, "a", "Show", 1)
    b = await _legacy(video_factory, "b", "Show", 2)
    c = await _legacy(video_factory, "c", "Show", 3)
    # And an earlier run already stored series "Show" as [a, b] and stopped there
    await SeriesModel(name="Show", videoIds=[a.id, b.id]).insert()

    # When the migration runs
    await _run()

    # Then exactly one series named "Show" exists, stored as [a, b, c]
    assert await SeriesModel.find({"name": "Show"}).count() == 1
    assert await stored_series("Show") == ["a", "b", "c"]
    # And c references it by seriesId
    assert await series_name_of(c) == "Show"


async def test_running_the_migration_twice_leaves_the_first_result_unchanged(video_factory):
    # Given videos a, b carrying seriesName "Show" with orders 2 and 1
    a = await _legacy(video_factory, "a", "Show", 2)
    b = await _legacy(video_factory, "b", "Show", 1)

    # When the migration runs twice
    await _run()
    await _run()

    # Then exactly one series named "Show" exists, stored as [b, a]
    assert await SeriesModel.find({"name": "Show"}).count() == 1
    assert await stored_series("Show") == ["b", "a"]
    # And a and b reference it by seriesId
    assert await series_name_of(a) == "Show"
    assert await series_name_of(b) == "Show"
