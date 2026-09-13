"""Unit tests for AbsolutePath — construction, validation, and path resolution."""

from unittest.mock import MagicMock
import pytest
from src.config import Settings
from src.errors import FileBrowseError
from src.platform.storage.absolute_path import AbsolutePath

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# --------------------------- Helpers ------------------------------------
# -----------------------------------------------------------------------

def _make_settings(resource_paths: dict[str, dict[str, str]]) -> Settings:
    return Settings.model_validate({"resource_paths": resource_paths})


def _make_handler() -> MagicMock:
    """A mock handler whose conversion methods are identity-ish."""
    h = MagicMock(name="handler")
    h.resolve_path.side_effect = lambda category, pseudo, sub: (
        category if pseudo is None else
        f"{category}/{pseudo}" if not sub else f"{category}/{pseudo}/{sub.lstrip('/')}"
    )
    h.convert_to_DB_format_path.side_effect = lambda p: f"DB::{p}"
    h.convert_to_FS_format_path.side_effect = lambda p: f"FS::{p}"
    h.get_path_standard_format.side_effect = lambda p: p
    return h


def _make_handler_service(handler) -> MagicMock:
    svc = MagicMock(name="HandlerService")
    svc.get_handler.return_value = handler
    return svc


# -----------------------------------------------------------------------
# --------------------- from_relative_path -------------------------------
# -----------------------------------------------------------------------

def test_from_relative_path_returns_root_when_parsed_is_none():
    abs_path = AbsolutePath.from_relative_path(parsedPath=None)
    assert abs_path.is_root_level()
    assert abs_path.abs_path is None
    assert abs_path.category is None
    assert abs_path.handler is None


def test_from_relative_path_returns_category_level():
    settings = _make_settings({"Cat": {"P1": "/data/p1"}})
    handler = _make_handler()
    svc = _make_handler_service(handler)

    abs_path = AbsolutePath.from_relative_path(
        parsedPath=("Cat", None, None), handlerService=svc, settings=settings,
    )
    assert abs_path.is_category_level()
    assert abs_path.category == "Cat"
    assert abs_path.abs_path == "Cat"
    handler.resolve_path.assert_called_once_with("Cat", None, None)


def test_from_relative_path_returns_resource_level():
    settings = _make_settings({"Cat": {"P1": "/data/p1"}})
    handler = _make_handler()
    svc = _make_handler_service(handler)

    abs_path = AbsolutePath.from_relative_path(
        parsedPath=("Cat", "P1", "/sub/dir"), handlerService=svc, settings=settings,
    )
    assert abs_path.abs_path == "Cat/P1/sub/dir"
    assert abs_path.category == "Cat"
    assert not abs_path.is_root_level()
    assert not abs_path.is_category_level()


def test_from_relative_path_unknown_category_raises():
    settings = _make_settings({"Cat": {"P1": "/data/p1"}})
    svc = _make_handler_service(_make_handler())

    with pytest.raises(FileBrowseError):
        AbsolutePath.from_relative_path(
            parsedPath=("Other", None, None), handlerService=svc, settings=settings,
        )


def test_from_relative_path_unknown_pseudo_name_raises():
    settings = _make_settings({"Cat": {"P1": "/data/p1"}})
    svc = _make_handler_service(_make_handler())

    with pytest.raises(FileBrowseError):
        AbsolutePath.from_relative_path(
            parsedPath=("Cat", "Unknown", None), handlerService=svc, settings=settings,
        )


# -----------------------------------------------------------------------
# --------------------- from_existing_path -------------------------------
# -----------------------------------------------------------------------

def test_from_existing_path_round_trip():
    handler = _make_handler()
    abs_path = AbsolutePath.from_existing_path(
        path="/x/y", category="Cat", handler=handler,
    )
    assert abs_path.abs_path == "/x/y"
    assert abs_path.category == "Cat"
    assert abs_path.handler is handler


# -----------------------------------------------------------------------
# --------------------- Conversion delegations ---------------------------
# -----------------------------------------------------------------------

def test_db_fs_get_paths_delegate_to_handler():
    handler = _make_handler()
    abs_path = AbsolutePath(abs_path="raw/x", category="Cat", handler=handler)

    assert abs_path.DB_format_path() == "DB::raw/x"
    assert abs_path.FS_format_path() == "FS::raw/x"
    assert abs_path.get_path() == "raw/x"


def test_conversions_return_none_when_abs_path_is_none():
    handler = _make_handler()
    abs_path = AbsolutePath(abs_path=None, category=None, handler=handler)

    assert abs_path.DB_format_path() is None
    assert abs_path.FS_format_path() is None
    assert abs_path.get_path() is None
    handler.convert_to_DB_format_path.assert_not_called()
    handler.convert_to_FS_format_path.assert_not_called()
    handler.get_path_standard_format.assert_not_called()


# -----------------------------------------------------------------------
# --------------------- update_path / level checks -----------------------
# -----------------------------------------------------------------------

def test_update_path_mutates_in_place():
    abs_path = AbsolutePath(abs_path="a", category="Cat", handler=None)
    abs_path.update_path("b")
    assert abs_path.abs_path == "b"
    assert abs_path.category == "Cat"


def test_is_root_level_only_when_both_none():
    assert AbsolutePath(None, None, None).is_root_level()
    assert not AbsolutePath("a", None, None).is_root_level()
    assert not AbsolutePath(None, "Cat", None).is_root_level()


def test_is_category_level_requires_abs_eq_category():
    assert AbsolutePath("Cat", "Cat", None).is_category_level()
    assert not AbsolutePath("Cat/sub", "Cat", None).is_category_level()
    assert not AbsolutePath(None, None, None).is_category_level()
