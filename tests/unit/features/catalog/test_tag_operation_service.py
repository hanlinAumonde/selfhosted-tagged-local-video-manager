"""Unit tests for TagOperationService — tag count updates and bulk operations."""

from unittest.mock import AsyncMock, patch

import pytest
from pymongo.errors import BulkWriteError

from src.features.catalog.video_tag import VideoTagModel
from src.features.catalog.tag_operation_service import TagOperationService

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# ----------------------- update_tag_counts ------------------------------
# -----------------------------------------------------------------------

async def test_increment_creates_new_tag(test_settings, init_db):
    svc = TagOperationService(settings=test_settings)
    await svc.update_tag_counts({"action": (1, True)})

    tag = await VideoTagModel.find_one({"name": "action"})
    assert tag is not None
    assert tag.tag_count == 1


async def test_increment_existing_tag(test_settings, init_db, tag_factory):
    await tag_factory(name="action", tag_count=3)
    svc = TagOperationService(settings=test_settings)
    await svc.update_tag_counts({"action": (2, True)})

    tag = await VideoTagModel.find_one({"name": "action"})
    assert tag.tag_count == 5


async def test_decrement_deletes_tag_at_zero(test_settings, init_db, tag_factory):
    await tag_factory(name="gone", tag_count=1)
    svc = TagOperationService(settings=test_settings)
    await svc.update_tag_counts({"gone": (1, False)})

    tag = await VideoTagModel.find_one({"name": "gone"})
    assert tag is None


async def test_decrement_below_zero_still_deleted(test_settings, init_db, tag_factory):
    await tag_factory(name="neg", tag_count=1)
    svc = TagOperationService(settings=test_settings)
    await svc.update_tag_counts({"neg": (5, False)})

    tag = await VideoTagModel.find_one({"name": "neg"})
    assert tag is None


async def test_mixed_increment_and_decrement(test_settings, init_db, tag_factory):
    await tag_factory(name="keep", tag_count=3)
    await tag_factory(name="drop", tag_count=1)

    svc = TagOperationService(settings=test_settings)
    await svc.update_tag_counts({
        "keep": (1, True),
        "drop": (1, False),
        "new": (1, True),
    })

    keep = await VideoTagModel.find_one({"name": "keep"})
    drop = await VideoTagModel.find_one({"name": "drop"})
    new = await VideoTagModel.find_one({"name": "new"})

    assert keep.tag_count == 4
    assert drop is None
    assert new is not None and new.tag_count == 1


async def test_empty_dict_is_noop(test_settings, init_db):
    svc = TagOperationService(settings=test_settings)
    await svc.update_tag_counts({})  # should not raise


# -----------------------------------------------------------------------
# ----------------------- track_tag_change -------------------------------
# -----------------------------------------------------------------------

def test_track_tag_change_accumulates(test_settings):
    svc = TagOperationService(settings=test_settings)
    update_tags: dict[str, tuple[int, bool]] = {}

    svc.track_tag_change(update_tags, {"a", "b"}, True)
    svc.track_tag_change(update_tags, {"b", "c"}, True)

    assert update_tags["a"] == (1, True)
    assert update_tags["b"] == (2, True)
    assert update_tags["c"] == (1, True)


def test_track_tag_change_decrement(test_settings):
    svc = TagOperationService(settings=test_settings)
    update_tags: dict[str, tuple[int, bool]] = {}

    svc.track_tag_change(update_tags, {"x"}, False)
    assert update_tags["x"] == (1, False)


# -----------------------------------------------------------------------
# ----------------------- get_top_tag_docs -------------------------------
# -----------------------------------------------------------------------

async def test_get_top_tags_returns_sorted_by_count(test_settings, init_db, tag_factory):
    await tag_factory(name="low", tag_count=1)
    await tag_factory(name="mid", tag_count=5)
    await tag_factory(name="high", tag_count=10)

    svc = TagOperationService(settings=test_settings)
    tags = await svc.get_top_tag_docs(limit=2)

    assert len(tags) == 2
    assert tags[0].name == "high"
    assert tags[1].name == "mid"


async def test_get_top_tags_returns_empty_when_no_categories(init_db):
    """With no configured categories, get_top_tag_docs returns empty."""
    from src.config import Settings
    empty = Settings.model_validate({"resource_paths": {}})
    svc = TagOperationService(settings=empty)
    assert await svc.get_top_tag_docs(limit=10) == []


# -----------------------------------------------------------------------
# ----------------------- exception handlers -----------------------------
# -----------------------------------------------------------------------

async def test_update_tag_counts_bulk_write_error_is_swallowed(test_settings, init_db):
    svc = TagOperationService(settings=test_settings)
    bwe = BulkWriteError({"writeErrors": [{"errmsg": "test"}]})
    with patch.object(
        VideoTagModel, "get_pymongo_collection",
        return_value=AsyncMock(bulk_write=AsyncMock(side_effect=bwe)),
    ):
        await svc.update_tag_counts({"action": (1, True)})


async def test_update_tag_counts_general_exception_is_swallowed(test_settings, init_db):
    svc = TagOperationService(settings=test_settings)
    with patch.object(
        VideoTagModel, "get_pymongo_collection",
        return_value=AsyncMock(bulk_write=AsyncMock(side_effect=RuntimeError("fail"))),
    ):
        await svc.update_tag_counts({"action": (1, True)})