"""Unit tests for ResourceHandlerService — handler creation and dispatch."""

import importlib
import pkgutil
import typing
from typing import Literal

import pytest
from pydantic import BaseModel

import src.platform.storage as storage_package
from src.config import HandlerConfig, Settings
from src.platform.storage import resource_handler_service
from src.platform.storage.base_resource_handler import BaseResourceHandler, HandlerBuildSpec
from src.platform.storage.local_fs.local_fs_handler import LocalFSResourceHandler
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.platform.storage.s3.s3_handler import S3ResourceHandler

pytestmark = pytest.mark.unit


S3_MOUNT = {
    "endpoint_url": "http://localhost:9999",
    "access_key": "test-key",
    "secret_key": "test-secret",
    "bucket": "video-app",
}


def _make_settings(resource_paths: dict[str, dict[str, str]]) -> Settings:
    return Settings.model_validate({"resource_paths": resource_paths})


# -----------------------------------------------------------------------
# ------------- Dispatch and lookup -------------------------------------
# -----------------------------------------------------------------------


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


# -----------------------------------------------------------------------
# ------------- The declared type picks the handler ---------------------
# -----------------------------------------------------------------------


class TestDispatchByDeclaredType:
    def test_category_with_no_handler_config_entry_gets_the_local_fs_handler(self):
        settings = _make_settings({"Cat": {"P1": "/data/p1"}})

        handler = ResourceHandlerService(settings=settings).get_handler("Cat")

        # Local stays the default, but as a declared default rather than as
        # "whatever is left once there is no S3 config".
        assert isinstance(handler, LocalFSResourceHandler)

    def test_category_declaring_s3_gets_an_s3_handler_carrying_its_mounts(self):
        settings = Settings.model_validate(
            {
                "resource_paths": {"S3-cat": {"Resource-1": "/"}},
                "handler_config": {"S3-cat": {"type": "s3", "mounts": {"Resource-1": S3_MOUNT}}},
            }
        )

        handler = ResourceHandlerService(settings=settings).get_handler("S3-cat")

        assert isinstance(handler, S3ResourceHandler)
        assert handler._configs["Resource-1"].bucket == "video-app"
        assert handler._configs["Resource-1"].endpoint_url == "http://localhost:9999"

    def test_two_categories_declaring_different_types_each_get_their_own_handler(self):
        settings = Settings.model_validate(
            {
                "resource_paths": {"Local-cat": {"P1": "/data/p1"}, "S3-cat": {"Resource-1": "/"}},
                "handler_config": {"S3-cat": {"type": "s3", "mounts": {"Resource-1": S3_MOUNT}}},
            }
        )
        svc = ResourceHandlerService(settings=settings)

        assert isinstance(svc.get_handler("Local-cat"), LocalFSResourceHandler)
        assert isinstance(svc.get_handler("S3-cat"), S3ResourceHandler)

    def test_a_type_with_no_handler_is_refused_and_the_error_names_the_known_ones(
        self, monkeypatch
    ):
        # A config model added without its handler. Naming the known types is
        # what tells the next person which half is missing; a bare lookup
        # failure would leave them with nothing to correct.
        monkeypatch.setattr(
            resource_handler_service,
            "_HANDLER_TYPES",
            {"local_fs": LocalFSResourceHandler},
        )
        settings = Settings.model_validate(
            {
                "resource_paths": {"S3-cat": {"Resource-1": "/"}},
                "handler_config": {"S3-cat": {"type": "s3", "mounts": {"Resource-1": S3_MOUNT}}},
            }
        )

        with pytest.raises(ValueError) as excinfo:
            ResourceHandlerService(settings=settings)

        assert "s3" in str(excinfo.value)
        assert "local_fs" in str(excinfo.value)


# -----------------------------------------------------------------------
# ------------- A backend the application does not ship -----------------
# -----------------------------------------------------------------------


class _InMemoryCategoryConfig(BaseModel):
    """The configuration shape a third backend would bring along."""

    type: Literal["in_memory"] = "in_memory"
    capacity: int = 10


def _refuse(*_args, **_kwargs):
    raise NotImplementedError("this stand-in performs no IO")


class _InMemoryResourceHandler(BaseResourceHandler):
    """Declares a type and knows how to build itself. It does no IO.

    What is under test is whether a backend the dispatcher has never heard of can
    be served by it, so the twenty IO methods are stubbed out rather than written.
    """

    storage_type = "in_memory"

    def __init__(self, spec: HandlerBuildSpec):
        self.spec = spec

    @classmethod
    def from_config(cls, spec: HandlerBuildSpec) -> "_InMemoryResourceHandler":
        return cls(spec)


for _name in BaseResourceHandler.__abstractmethods__:
    if _name not in vars(_InMemoryResourceHandler):
        setattr(_InMemoryResourceHandler, _name, _refuse)
_InMemoryResourceHandler.__abstractmethods__ = frozenset()


class TestAddingABackend:
    def test_a_backend_the_dispatcher_never_heard_of_is_served_by_it_unchanged(
        self, monkeypatch
    ):
        # The extensibility claim: a new storage type costs a table entry and a
        # config model, and no edit to _create_handler.
        config = _InMemoryCategoryConfig(capacity=42)
        monkeypatch.setattr(
            resource_handler_service,
            "_HANDLER_TYPES",
            dict(resource_handler_service._HANDLER_TYPES, in_memory=_InMemoryResourceHandler),
        )
        monkeypatch.setattr(Settings, "get_handler_config", lambda self, category: config)
        settings = _make_settings({"Memory-cat": {"Resource-1": "/wherever"}})

        handler = ResourceHandlerService(settings=settings).get_handler("Memory-cat")

        assert isinstance(handler, _InMemoryResourceHandler)
        assert handler.spec.category == "Memory-cat"
        assert handler.spec.pseudo_paths == {"Resource-1": "/wherever"}
        # Each handler receives its own slice of configuration, not the whole file.
        assert handler.spec.config.capacity == 42


# -----------------------------------------------------------------------
# ------------- Guards: the two halves must stay in step ----------------
# -----------------------------------------------------------------------


def _declared_config_tags() -> set[str]:
    """The ``type`` tags the HandlerConfig union accepts."""
    union = typing.get_args(HandlerConfig)[0]
    return {
        typing.get_args(member.model_fields["type"].annotation)[0]
        for member in typing.get_args(union)
    }


def _concrete_handlers_in_storage_package() -> set[type[BaseResourceHandler]]:
    for module in pkgutil.walk_packages(
        storage_package.__path__, prefix="src.platform.storage."
    ):
        importlib.import_module(module.name)

    found: set[type[BaseResourceHandler]] = set()
    pending = list(BaseResourceHandler.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls.__abstractmethods__:
            continue
        if cls.__module__.startswith("src.platform.storage"):
            found.add(cls)
    return found


class TestBackendRegistrationGuards:
    def test_every_declared_config_type_has_a_handler_and_the_reverse(self):
        # A storage type is declared in two places -- a config model in config.py
        # and an entry in the dispatcher's table. Adding one without the other
        # fails here, rather than as a crash for whoever first writes that type
        # into their config.
        assert _declared_config_tags() == set(resource_handler_service._HANDLER_TYPES)

    def test_every_concrete_handler_in_the_storage_package_is_reachable(self):
        listed = set(resource_handler_service._HANDLER_TYPES.values())
        unlisted = _concrete_handlers_in_storage_package() - listed

        # Writing a handler and wiring it up nowhere fails here, not at a user's
        # first request against that category.
        assert not unlisted, f"unlisted handlers: {sorted(c.__name__ for c in unlisted)}"
