"""Unit tests for CacheService — backend selection and cache operations."""

from unittest.mock import MagicMock

import pytest

from src.config import CacheConfig
from src.platform.cache.cache_service import CacheService
from src.platform.cache.cachetools_cache import CachetoolsCache

pytestmark = pytest.mark.unit


def test_cachetools_backend_is_selected_by_default():
    svc = CacheService(config=CacheConfig())
    assert isinstance(svc._impl, CachetoolsCache)


def test_unsupported_cache_type_raises():
    with pytest.raises(ValueError):
        CacheService(config=CacheConfig(cache_type="redis"))


def test_set_get_round_trip_through_service():
    svc = CacheService(config=CacheConfig())
    svc.set("k", "value")
    assert svc.get("k") == "value"
    assert svc.contains("k") is True


def test_delete_through_service():
    svc = CacheService(config=CacheConfig())
    svc.set("k", "value")
    svc.delete("k")
    assert svc.get("k") is None
    assert svc.contains("k") is False


def test_clear_through_service():
    svc = CacheService(config=CacheConfig())
    svc.set("a", 1)
    svc.set("b", 2)
    svc.clear()
    assert svc.contains("a") is False
    assert svc.contains("b") is False


def test_methods_delegate_to_underlying_impl():
    """Each public method should forward to the underlying implementation."""
    svc = CacheService(config=CacheConfig())
    svc._impl = MagicMock(name="impl")

    svc.get("k")
    svc._impl.get.assert_called_once_with("k")

    svc.set("k", 1)
    svc._impl.set.assert_called_once_with("k", 1)

    svc.delete("k")
    svc._impl.delete.assert_called_once_with("k")

    svc.contains("k")
    svc._impl.contains.assert_called_once_with("k")

    svc.clear()
    svc._impl.clear.assert_called_once_with()
