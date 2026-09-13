"""Unit tests for ResourceHandlerService — handler creation and dispatch."""

import pytest

from src.config import Settings
from src.platform.storage.local_fs.local_fs_handler import LocalFSResourceHandler
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit


def _make_settings(resource_paths: dict[str, dict[str, str]]) -> Settings:
    return Settings.model_validate({"resource_paths": resource_paths})


def test_dispatcher_creates_local_handler_when_no_s3_config():
    settings = _make_settings({"Cat": {"P1": "/data/p1"}})
    svc = ResourceHandlerService(settings=settings)

    handler = svc.get_handler("Cat")
    assert isinstance(handler, LocalFSResourceHandler)


def test_get_handler_unknown_category_raises():
    svc = ResourceHandlerService(settings=_make_settings({"Cat": {"P1": "/data/p1"}}))
    with pytest.raises(ValueError):
        svc.get_handler("Other")


def test_get_all_categories_lists_every_configured_one():
    settings = _make_settings({"A": {"P1": "/a"}, "B": {"P2": "/b"}})
    svc = ResourceHandlerService(settings=settings)
    assert set(svc.get_all_categories()) == {"A", "B"}


def test_get_pseudo_names_lists_every_configured_one():
    settings = _make_settings({"A": {"P1": "/a", "P2": "/a2"}})
    svc = ResourceHandlerService(settings=settings)
    assert set(svc.get_pseudo_names("A")) == {"P1", "P2"}


def test_get_pseudo_names_unknown_category_raises():
    svc = ResourceHandlerService(settings=_make_settings({"A": {"P1": "/a"}}))
    with pytest.raises(ValueError):
        svc.get_pseudo_names("Z")


def test_each_category_gets_a_distinct_handler_instance():
    settings = _make_settings({"A": {"P1": "/a"}, "B": {"P2": "/b"}})
    svc = ResourceHandlerService(settings=settings)
    assert svc.get_handler("A") is not svc.get_handler("B")
    # ``get_handler`` returns the same instance on repeated calls (cached).
    assert svc.get_handler("A") is svc.get_handler("A")
