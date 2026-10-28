"""Unit tests for RedisCache — run against a real Redis testcontainer."""

import asyncio

import pytest

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# ----------------------- read / write ----------------------------------
# -----------------------------------------------------------------------

async def test_get_returns_none_for_missing_key(redis_cache):
    # Given a RedisCache connected to a running Redis
    # When a key that was never written is read
    # Then None is returned
    assert await redis_cache.get("missing") is None


async def test_set_and_get_round_trip(redis_cache):
    # Given a RedisCache connected to a running Redis
    # When a JSON-serialisable value is written and then read back
    # Then the same value is returned
    await redis_cache.set("k", {"size": 10, "names": ["a", "b"]}, ttl=60)
    assert await redis_cache.get("k") == {"size": 10, "names": ["a", "b"]}


async def test_tuple_value_comes_back_as_list(redis_cache):
    # Given a RedisCache connected to a running Redis
    # When the tuple (1.0, 2.0) is written and then read back
    # Then the value read is the list [1.0, 2.0] — the JSON contract every backend shares
    await redis_cache.set("k", (1.0, 2.0), ttl=60)
    assert await redis_cache.get("k") == [1.0, 2.0]


async def test_keys_are_stored_under_the_configured_prefix(redis_cache, raw_redis, prefix):
    # Given a RedisCache whose key_prefix is "pfx"
    # When the key "a:b" is written
    # Then the raw Redis key "pfx:a:b" exists and the bare key "a:b" does not
    await redis_cache.set("a:b", 1, ttl=60)
    assert raw_redis.exists(f"{prefix}:a:b") == 1
    assert raw_redis.exists("a:b") == 0


async def test_delete_removes_entry(redis_cache):
    # Given a RedisCache holding key "k"
    # When "k" is deleted
    # Then get("k") returns None and contains("k") is False
    await redis_cache.set("k", "v", ttl=60)
    await redis_cache.delete("k")
    assert await redis_cache.get("k") is None
    assert await redis_cache.contains("k") is False


async def test_contains_reflects_current_state(redis_cache):
    # Given a RedisCache with nothing under key "k"
    # When contains("k") is asked before and after writing "k"
    # Then the answers are False and then True
    assert await redis_cache.contains("k") is False
    await redis_cache.set("k", 1, ttl=60)
    assert await redis_cache.contains("k") is True


# -----------------------------------------------------------------------
# ----------------------- TTL -------------------------------------------
# -----------------------------------------------------------------------

async def test_set_applies_the_given_ttl(redis_cache, raw_redis, prefix):
    # Given a RedisCache connected to a running Redis
    # When key "k" is written with ttl=120
    # Then Redis reports a remaining TTL on "pfx:k" between 1 and 120 seconds
    await redis_cache.set("k", 1, ttl=120)
    assert 0 < raw_redis.ttl(f"{prefix}:k") <= 120


async def test_entry_expires_after_its_ttl(redis_cache):
    # Given a RedisCache holding key "k" written with ttl=1
    # When more than one second passes
    # Then get("k") returns None
    await redis_cache.set("k", 1, ttl=1)
    await asyncio.sleep(1.5)
    assert await redis_cache.get("k") is None


# -----------------------------------------------------------------------
# ----------------------- set_many --------------------------------------
# -----------------------------------------------------------------------

async def test_set_many_writes_every_entry(redis_cache):
    # Given a RedisCache connected to a running Redis
    # When set_many is called with three keys holding different values
    # Then each of the three keys reads back its own value
    await redis_cache.set_many({"a": [1.0, 2.0], "b": [3.0, 4.0], "c": "x"}, ttl=60)
    assert await redis_cache.get("a") == [1.0, 2.0]
    assert await redis_cache.get("b") == [3.0, 4.0]
    assert await redis_cache.get("c") == "x"


async def test_set_many_applies_the_ttl_to_every_entry(redis_cache, raw_redis, prefix):
    # Given a RedisCache connected to a running Redis
    # When set_many writes three keys with ttl=120
    # Then every one of the three raw keys has a remaining TTL between 1 and 120 seconds
    await redis_cache.set_many({"a": 1, "b": 2, "c": 3}, ttl=120)
    for key in ("a", "b", "c"):
        assert 0 < raw_redis.ttl(f"{prefix}:{key}") <= 120


async def test_set_many_with_no_entries_is_a_no_op(redis_cache, raw_redis, prefix):
    # Given a RedisCache whose prefix currently holds no keys
    # When set_many is called with an empty mapping
    # Then no error is raised and the prefix still holds no keys
    await redis_cache.set_many({}, ttl=60)
    assert list(raw_redis.scan_iter(match=f"{prefix}:*")) == []


# -----------------------------------------------------------------------
# ----------------------- clear -----------------------------------------
# -----------------------------------------------------------------------

async def test_clear_removes_every_key_under_the_prefix(redis_cache):
    # Given a RedisCache with prefix "pfx" holding keys "a" and "b"
    # When clear() is called
    # Then neither "a" nor "b" can be read any more
    await redis_cache.set_many({"a": 1, "b": 2}, ttl=60)
    await redis_cache.clear()
    assert await redis_cache.get("a") is None
    assert await redis_cache.get("b") is None


async def test_clear_removes_more_keys_than_one_unlink_batch(redis_cache, raw_redis, prefix):
    # Given a RedisCache whose prefix holds 1200 keys — more than one unlink batch of 500
    # When clear() is called
    # Then no key under the prefix remains
    await redis_cache.set_many({f"k{i}": i for i in range(1200)}, ttl=60)
    await redis_cache.clear()
    assert list(raw_redis.scan_iter(match=f"{prefix}:*")) == []


async def test_clear_leaves_keys_outside_the_prefix_untouched(redis_cache, raw_redis):
    # Given a Redis that holds the raw key "other:x" written by someone else
    # And a RedisCache with prefix "pfx" holding key "a"
    # When clear() is called on that RedisCache
    # Then "other:x" still exists in Redis
    raw_redis.set("other:x", "keep-me")
    try:
        await redis_cache.set("a", 1, ttl=60)
        await redis_cache.clear()
        assert raw_redis.get("other:x") == "keep-me"
    finally:
        raw_redis.delete("other:x")


# -----------------------------------------------------------------------
# ----------------------- degradation when Redis is unreachable ---------
# -----------------------------------------------------------------------

async def test_get_degrades_to_a_miss_when_redis_is_unreachable(
    unreachable_redis_cache, captured_warnings,
):
    # Given a RedisCache pointed at an address where no Redis is listening
    # When get("k") is called
    # Then None is returned instead of an exception being raised
    # And a warning is logged
    assert await unreachable_redis_cache.get("k") is None
    assert len(captured_warnings.messages) == 1


async def test_contains_degrades_to_false_when_redis_is_unreachable(unreachable_redis_cache):
    # Given a RedisCache pointed at an address where no Redis is listening
    # When contains("k") is called
    # Then False is returned instead of an exception being raised
    assert await unreachable_redis_cache.contains("k") is False


async def test_writes_are_silently_dropped_when_redis_is_unreachable(
    unreachable_redis_cache, captured_warnings,
):
    # Given a RedisCache pointed at an address where no Redis is listening
    # When set, set_many, delete and clear are each called
    # Then none of them raises
    # And a warning is logged for each failed call
    await unreachable_redis_cache.set("k", 1, ttl=60)
    await unreachable_redis_cache.set_many({"a": 1, "b": 2}, ttl=60)
    await unreachable_redis_cache.delete("k")
    await unreachable_redis_cache.clear()
    assert len(captured_warnings.messages) == 4
