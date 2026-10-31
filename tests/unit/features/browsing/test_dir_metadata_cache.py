"""How DirMetadataService uses its cache: per-purpose TTL, batched writes, value shape."""

from unittest.mock import patch

import pytest

from src.config import Settings
from src.features.browsing.dir_metadata import DirMetadataModel
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.cache.cache_service import CacheService
from src.platform.storage.resource_handler_service import ResourceHandlerService
from tests.cache_helpers import advance_cache_clock

pytestmark = pytest.mark.unit

CATEGORY = "Test-category"
DIR_TTL = 60


@pytest.fixture
def ttl_settings(fs_settings: Settings) -> Settings:
    payload = fs_settings.model_dump()
    payload["cache_config"]["ttl"]["dir_metadata"] = DIR_TTL
    return Settings.model_validate(payload)


@pytest.fixture
def cache(ttl_settings: Settings) -> CacheService:
    return CacheService(config=ttl_settings.cache_config)


@pytest.fixture
def svc(
    ttl_settings: Settings,
    local_resource_handler_service: ResourceHandlerService,
    cache: CacheService,
) -> DirMetadataService:
    return DirMetadataService(
        settings=ttl_settings,
        resource_handler_service=local_resource_handler_service,
        cache_service=cache,
    )


async def _drop_db_records() -> None:
    """Leave the cache as the only place the metadata can come from."""
    await DirMetadataModel.find({"category": CATEGORY}).delete()


async def test_cached_metadata_is_returned_as_a_tuple(svc, init_db):
    # Given metadata (42.0, 99.0) written for a directory through set_metadata
    # When get_metadata is called for that directory and the answer comes from the cache
    # Then the result is the tuple (42.0, 99.0), not the list the cache stores
    await svc.set_metadata(CATEGORY, "a/b", 42.0, 99.0)
    await _drop_db_records()

    result = await svc.get_metadata(CATEGORY, "a/b")

    assert result == (42.0, 99.0)
    assert isinstance(result, tuple)


async def test_cache_entry_lives_for_the_dir_metadata_ttl(svc, cache, init_db):
    # Given cache_config.ttl.dir_metadata is 60 and the database record is removed after writing
    # And metadata written for a directory through set_metadata
    # When the cache clock advances by 59 seconds
    # Then get_metadata still answers from the cache
    await svc.set_metadata(CATEGORY, "a/b", 42.0, 99.0)
    await _drop_db_records()

    advance_cache_clock(cache, DIR_TTL - 1)

    assert await svc.get_metadata(CATEGORY, "a/b") == (42.0, 99.0)


async def test_cache_entry_expires_after_the_dir_metadata_ttl(svc, cache, init_db):
    # Given cache_config.ttl.dir_metadata is 60 and the database record is removed after writing
    # And metadata written for a directory through set_metadata
    # When the cache clock advances by 61 seconds
    # Then get_metadata finds nothing in the cache or the database and returns None
    await svc.set_metadata(CATEGORY, "a/b", 42.0, 99.0)
    await _drop_db_records()

    advance_cache_clock(cache, DIR_TTL + 1)

    assert await svc.get_metadata(CATEGORY, "a/b") is None


async def test_bulk_set_metadata_writes_all_entries_with_one_batched_cache_call(
    svc, cache, init_db,
):
    # Given three directories with different (size, mtime) pairs
    # When bulk_set_metadata is called with all three
    # Then the cache receives exactly one set_many call and no single set calls
    # And every one of the three directories reads back its own pair from the cache
    entries = {"d/a": (10.0, 1.0), "d/b": (20.0, 2.0), "d/c": (30.0, 3.0)}

    with patch.object(cache, "set_many", wraps=cache.set_many) as set_many, \
         patch.object(cache, "set", wraps=cache.set) as single_set:
        await svc.bulk_set_metadata(CATEGORY, entries)

    assert set_many.await_count == 1
    assert single_set.await_count == 0

    await _drop_db_records()
    assert await svc.get_metadata(CATEGORY, "d/a") == (10.0, 1.0)
    assert await svc.get_metadata(CATEGORY, "d/b") == (20.0, 2.0)
    assert await svc.get_metadata(CATEGORY, "d/c") == (30.0, 3.0)


async def test_bulk_set_metadata_entries_use_the_dir_metadata_ttl(svc, cache, init_db):
    # Given cache_config.ttl.dir_metadata is 60 and the database records are removed after writing
    # And two directories written through bulk_set_metadata
    # When the cache clock advances by 61 seconds
    # Then get_metadata returns None for both directories
    await svc.bulk_set_metadata(CATEGORY, {"d/a": (10.0, 1.0), "d/b": (20.0, 2.0)})
    await _drop_db_records()

    advance_cache_clock(cache, DIR_TTL + 1)

    assert await svc.get_metadata(CATEGORY, "d/a") is None
    assert await svc.get_metadata(CATEGORY, "d/b") is None
