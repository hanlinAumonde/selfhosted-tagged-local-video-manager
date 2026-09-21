"""Unit tests for CachetoolsCache — get, set, delete, and TTL behaviour."""

import pytest

from src.platform.cache.cachetools_cache import CachetoolsCache

pytestmark = pytest.mark.unit


def test_get_returns_none_for_missing_key():
    cache = CachetoolsCache(maxsize=10, ttl=60)
    assert cache.get("missing") is None


def test_set_and_get_round_trip():
    cache = CachetoolsCache(maxsize=10, ttl=60)
    cache.set("k", "value")
    assert cache.get("k") == "value"


def test_set_overwrites_existing_value():
    cache = CachetoolsCache(maxsize=10, ttl=60)
    cache.set("k", "first")
    cache.set("k", "second")
    assert cache.get("k") == "second"


def test_delete_removes_entry():
    cache = CachetoolsCache(maxsize=10, ttl=60)
    cache.set("k", "v")
    cache.delete("k")
    assert cache.get("k") is None
    assert cache.contains("k") is False


def test_delete_missing_key_is_silent():
    cache = CachetoolsCache(maxsize=10, ttl=60)
    cache.delete("never-set")  # should not raise


def test_contains_reflects_current_state():
    cache = CachetoolsCache(maxsize=10, ttl=60)
    assert cache.contains("k") is False
    cache.set("k", 1)
    assert cache.contains("k") is True


def test_clear_empties_cache():
    cache = CachetoolsCache(maxsize=10, ttl=60)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_ttl_expiry_drops_old_entries():
    cache = CachetoolsCache(maxsize=10, ttl=60)
    cache.set("k", "v")
    assert cache.get("k") == "v"

    # Fast-forward the underlying TTLCache clock past the entry's expiry.
    underlying = cache._cache
    underlying.expire(underlying.timer() + 120)
    assert cache.get("k") is None
    assert cache.contains("k") is False


def test_maxsize_evicts_oldest_when_full():
    cache = CachetoolsCache(maxsize=2, ttl=600)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)  # evicts the LRU/oldest entry
    # After eviction, only 2 entries remain. Confirm by counting.
    survived = sum(1 for k in ("a", "b", "c") if cache.contains(k))
    assert survived == 2
