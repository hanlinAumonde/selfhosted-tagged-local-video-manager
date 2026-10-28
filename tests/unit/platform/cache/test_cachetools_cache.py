"""Unit tests for CachetoolsCache — get, set, delete, and per-entry TTL behaviour."""

import pytest

from src.platform.cache.cachetools_cache import CachetoolsCache
from tests.cache_helpers import advance_cache_clock

pytestmark = pytest.mark.unit


@pytest.fixture
def cache() -> CachetoolsCache:
    return CachetoolsCache(max_size=10, key_prefix="pfx")


# -----------------------------------------------------------------------
# ----------------------- read / write ----------------------------------
# -----------------------------------------------------------------------

async def test_get_returns_none_for_missing_key(cache):
    # Given an empty CachetoolsCache
    # When a key that was never written is read
    # Then None is returned
    assert await cache.get("missing") is None


async def test_set_and_get_round_trip(cache):
    # Given an empty CachetoolsCache
    # When a JSON-serialisable value is written and then read back
    # Then the same value is returned
    await cache.set("k", {"size": 10, "names": ["a", "b"]}, ttl=60)
    assert await cache.get("k") == {"size": 10, "names": ["a", "b"]}


async def test_tuple_value_comes_back_as_list(cache):
    # Given an empty CachetoolsCache
    # When the tuple (1.0, 2.0) is written and then read back
    # Then the value read is the list [1.0, 2.0], exactly as the Redis backend returns it
    await cache.set("k", (1.0, 2.0), ttl=60)
    assert await cache.get("k") == [1.0, 2.0]


async def test_mutating_a_value_after_set_does_not_change_the_cached_copy(cache):
    # Given a CachetoolsCache holding the list [1, 2] under key "k"
    # When the caller's list is mutated after the write
    # Then get("k") still returns [1, 2]
    value = [1, 2]
    await cache.set("k", value, ttl=60)
    value.append(3)
    assert await cache.get("k") == [1, 2]


async def test_set_overwrites_existing_value(cache):
    # Given a CachetoolsCache holding "first" under key "k"
    # When "second" is written under "k"
    # Then get("k") returns "second"
    await cache.set("k", "first", ttl=60)
    await cache.set("k", "second", ttl=60)
    assert await cache.get("k") == "second"


async def test_delete_removes_entry(cache):
    # Given a CachetoolsCache holding key "k"
    # When "k" is deleted
    # Then get("k") returns None and contains("k") is False
    await cache.set("k", "v", ttl=60)
    await cache.delete("k")
    assert await cache.get("k") is None
    assert await cache.contains("k") is False


async def test_delete_missing_key_is_silent(cache):
    # Given an empty CachetoolsCache
    # When a key that was never written is deleted
    # Then no error is raised
    await cache.delete("never-set")


async def test_contains_reflects_current_state(cache):
    # Given a CachetoolsCache with nothing under key "k"
    # When contains("k") is asked before and after writing "k"
    # Then the answers are False and then True
    assert await cache.contains("k") is False
    await cache.set("k", 1, ttl=60)
    assert await cache.contains("k") is True


async def test_clear_empties_cache(cache):
    # Given a CachetoolsCache holding keys "a" and "b"
    # When clear() is called
    # Then neither "a" nor "b" can be read any more
    await cache.set("a", 1, ttl=60)
    await cache.set("b", 2, ttl=60)
    await cache.clear()
    assert await cache.get("a") is None
    assert await cache.get("b") is None


# -----------------------------------------------------------------------
# ----------------------- set_many --------------------------------------
# -----------------------------------------------------------------------

async def test_set_many_writes_every_entry(cache):
    # Given an empty CachetoolsCache
    # When set_many is called with three keys holding different values
    # Then each of the three keys reads back its own value
    await cache.set_many({"a": [1.0, 2.0], "b": [3.0, 4.0], "c": "x"}, ttl=60)
    assert await cache.get("a") == [1.0, 2.0]
    assert await cache.get("b") == [3.0, 4.0]
    assert await cache.get("c") == "x"


# -----------------------------------------------------------------------
# ----------------------- per-entry TTL ---------------------------------
# -----------------------------------------------------------------------

async def test_entry_survives_until_its_ttl_elapses(cache):
    # Given a CachetoolsCache holding key "k" written with ttl=60
    # When the cache clock advances by 59 seconds
    # Then get("k") still returns the value
    await cache.set("k", "v", ttl=60)
    advance_cache_clock(cache, 59)
    assert await cache.get("k") == "v"


async def test_entry_expires_after_its_ttl(cache):
    # Given a CachetoolsCache holding key "k" written with ttl=60
    # When the cache clock advances by 61 seconds
    # Then get("k") returns None and contains("k") is False
    await cache.set("k", "v", ttl=60)
    advance_cache_clock(cache, 61)
    assert await cache.get("k") is None
    assert await cache.contains("k") is False


async def test_entries_with_different_ttls_expire_independently(cache):
    # Given a CachetoolsCache holding "short" written with ttl=10 and "long" written with ttl=100
    # When the cache clock advances by 50 seconds
    # Then "short" is gone and "long" is still readable
    await cache.set("short", 1, ttl=10)
    await cache.set("long", 2, ttl=100)
    advance_cache_clock(cache, 50)
    assert await cache.get("short") is None
    assert await cache.get("long") == 2


async def test_set_many_applies_the_ttl_to_every_entry(cache):
    # Given a CachetoolsCache in which set_many wrote "a" and "b" with ttl=60
    # When the cache clock advances by 61 seconds
    # Then neither "a" nor "b" can be read any more
    await cache.set_many({"a": 1, "b": 2}, ttl=60)
    advance_cache_clock(cache, 61)
    assert await cache.get("a") is None
    assert await cache.get("b") is None


# -----------------------------------------------------------------------
# ----------------------- capacity --------------------------------------
# -----------------------------------------------------------------------

async def test_max_size_evicts_when_full():
    # Given a CachetoolsCache with max_size=2 holding "a" and "b"
    # When a third key "c" is written
    # Then exactly two of the three keys remain readable
    cache = CachetoolsCache(max_size=2, key_prefix="pfx")
    await cache.set("a", 1, ttl=600)
    await cache.set("b", 2, ttl=600)
    await cache.set("c", 3, ttl=600)
    survived = [k for k in ("a", "b", "c") if await cache.contains(k)]
    assert len(survived) == 2
