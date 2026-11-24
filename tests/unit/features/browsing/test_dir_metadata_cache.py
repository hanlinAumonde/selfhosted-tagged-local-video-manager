"""How DirMetadataService uses its cache: per-purpose TTL, batched writes, value shape."""

from unittest.mock import patch

import pytest

from src.config import Settings
from src.features.browsing.dir_metadata_model import DirMetadataModel
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.redis.redis_cache import RedisCache
from src.platform.redis.redis_service import RedisService
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit

CATEGORY = "Test-category"
DIR_TTL = 60


@pytest.fixture
def ttl_settings(fs_settings: Settings) -> Settings:
    payload = fs_settings.model_dump()
    payload["cache_config"]["ttl"]["dir_metadata"] = DIR_TTL
    return Settings.model_validate(payload)


@pytest.fixture
def svc(
    ttl_settings: Settings,
    local_resource_handler_service: ResourceHandlerService,
    redis_cache: RedisCache,
) -> DirMetadataService:
    return DirMetadataService(
        settings=ttl_settings,
        resource_handler_service=local_resource_handler_service,
        cache=redis_cache,
    )


async def _remaining_ttl(redis_service: RedisService, prefix: str, path: str) -> int:
    return await redis_service.client.ttl(f"{prefix}:cache:{CATEGORY}:{path}")


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


async def test_set_metadata_writes_its_cache_entry_with_the_dir_metadata_ttl(
    svc, redis_service, redis_prefix, init_db,
):
    # Given cache_config.ttl.dir_metadata is 60
    # When metadata is written for directory "a/b" through set_metadata
    await svc.set_metadata(CATEGORY, "a/b", 42.0, 99.0)

    # Then the directory's raw cache key has a remaining TTL above 55 and at most 60 seconds
    assert 55 < await _remaining_ttl(redis_service, redis_prefix, "a/b") <= DIR_TTL


async def test_bulk_set_metadata_writes_all_entries_with_one_batched_cache_call(
    svc, redis_cache, init_db,
):
    # Given three directories with different (size, mtime) pairs
    # When bulk_set_metadata is called with all three
    # Then the cache receives exactly one set_many call and no single set calls
    # And every one of the three directories reads back its own pair from the cache
    entries = {"d/a": (10.0, 1.0), "d/b": (20.0, 2.0), "d/c": (30.0, 3.0)}

    with patch.object(redis_cache, "set_many", wraps=redis_cache.set_many) as set_many, \
         patch.object(redis_cache, "set", wraps=redis_cache.set) as single_set:
        await svc.bulk_set_metadata(CATEGORY, entries)

    assert set_many.await_count == 1
    assert single_set.await_count == 0

    await _drop_db_records()
    assert await svc.get_metadata(CATEGORY, "d/a") == (10.0, 1.0)
    assert await svc.get_metadata(CATEGORY, "d/b") == (20.0, 2.0)
    assert await svc.get_metadata(CATEGORY, "d/c") == (30.0, 3.0)


async def test_bulk_set_metadata_writes_every_entry_with_the_dir_metadata_ttl(
    svc, redis_service, redis_prefix, init_db,
):
    # Given cache_config.ttl.dir_metadata is 60
    # When directories "d/a" and "d/b" are written through bulk_set_metadata
    await svc.bulk_set_metadata(CATEGORY, {"d/a": (10.0, 1.0), "d/b": (20.0, 2.0)})

    # Then each of the two raw cache keys has a remaining TTL above 55 and at most 60 seconds
    assert 55 < await _remaining_ttl(redis_service, redis_prefix, "d/a") <= DIR_TTL
    assert 55 < await _remaining_ttl(redis_service, redis_prefix, "d/b") <= DIR_TTL
