"""
Behaviour specification — every storage-touching handler method is a coroutine.

A blocked event loop is paid for by every concurrent request: one ``stat`` stuck on a
sleeping NAS stalls every video being streamed at that moment. So the rule is
structural, not a matter of reviewing each call site: anything on ``BaseResourceHandler``
that may reach the storage is ``async``, and only an explicit list of pure path
computations stays synchronous.
"""

import inspect

import pytest

from src.platform.storage.base_resource_handler import BaseResourceHandler
from src.platform.storage.resource_handler_service import _HANDLER_TYPES

pytestmark = pytest.mark.unit

#: Computed from the path alone. A pre-signed S3 URL belongs here too: the signature is
#: calculated locally, no request is sent.
PURE_METHODS = {
    "from_config",
    "resolve_path",
    "convert_to_DB_format_path",
    "convert_to_FS_format_path",
    "get_path_standard_format",
    "get_ffmpeg_accessible_path",
    "is_video_file",
    "get_file_extension",
    "get_filename_without_extension",
    "join_path",
    "dirname",
}


def _is_async(fn) -> bool:
    return inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn)


def _public_methods(cls: type) -> dict[str, object]:
    return {
        name: member
        for name, member in inspect.getmembers(cls)
        if not name.startswith("_") and callable(member)
    }


# Scenario: a new IO method cannot be added to the handler interface as a plain function
#   Given the public methods declared on BaseResourceHandler
#   And an explicit list of pure path computations (convert_to_*, join_path, dirname,
#       is_video_file, resolve_path, get_ffmpeg_accessible_path, ...)
#   When every method outside that list is inspected
#   Then each is a coroutine function or an async generator function
def test_every_non_pure_handler_method_is_async():
    offenders = sorted(
        name
        for name, member in _public_methods(BaseResourceHandler).items()
        if name not in PURE_METHODS and not _is_async(member)
    )

    assert offenders == [], f"handler methods that may touch storage but are sync: {offenders}"


# Scenario: the pure list does not silently keep a method that no longer exists
#   Given the explicit list of pure method names
#   When each name is looked up on BaseResourceHandler
#   Then every name resolves to a method — a stale entry would exempt nothing yet read
#       as if it did
def test_pure_method_list_names_only_existing_methods():
    stale = sorted(name for name in PURE_METHODS if not hasattr(BaseResourceHandler, name))

    assert stale == []


# Scenario: each concrete handler keeps the contract its base declares
#   Given every concrete handler class registered in the dispatcher
#   When each overridden non-pure method is inspected
#   Then it is async too — an override written as a plain def would block the loop
#       while the base signature says it does not
@pytest.mark.parametrize("handler_cls", sorted(_HANDLER_TYPES.values(), key=lambda c: c.__name__))
def test_concrete_handlers_do_not_override_an_async_method_with_a_sync_one(handler_cls):
    offenders = sorted(
        name
        for name, member in _public_methods(handler_cls).items()
        if name not in PURE_METHODS and not _is_async(member)
    )

    assert offenders == [], f"{handler_cls.__name__} sync IO methods: {offenders}"
