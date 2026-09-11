"""
The generic path-lock registry.

Answers "is this path held by a job that has not settled?" without knowing what kind of
job holds it. Providers register at startup, the same way executors register on the
TaskRunner, so a second kind of task can reserve files without the readers that display
them learning anything new.
"""

import ast
from pathlib import Path

import pytest

from src.platform.jobs.path_locks import PathLockRegistry

pytestmark = pytest.mark.unit

PATH_LOCKS_SOURCE = (
    Path(__file__).resolve().parents[3] / "src" / "platform" / "jobs" / "path_locks.py"
)


class _StubProvider:
    """A provider that reports a fixed set, and records what it was asked."""

    def __init__(self, locked: set[str] | None = None):
        self._locked = locked or set()
        self.calls: list[set[str]] = []

    async def locked_paths(self, db_paths) -> set[str]:
        wanted = set(db_paths)
        self.calls.append(wanted)
        return self._locked & wanted


class _FailingProvider:
    """A provider whose backing store is broken."""

    async def locked_paths(self, db_paths) -> set[str]:
        raise RuntimeError("database unreachable")


# -----------------------------------------------------------------------
# ---------- Fanning out to providers ------------------------------------
# -----------------------------------------------------------------------

async def test_returns_nothing_when_no_provider_is_registered():
    registry = PathLockRegistry()

    assert await registry.locked_paths(["a.mp4", "b.mp4"]) == set()


async def test_returns_what_the_single_provider_reports():
    registry = PathLockRegistry()
    registry.register("stub", _StubProvider({"a.mp4"}))

    assert await registry.locked_paths(["a.mp4", "b.mp4"]) == {"a.mp4"}


async def test_unions_the_reports_of_every_provider():
    registry = PathLockRegistry()
    registry.register("copies", _StubProvider({"a.mp4"}))
    registry.register("transcodes", _StubProvider({"b.mp4"}))

    assert await registry.locked_paths(["a.mp4", "b.mp4"]) == {"a.mp4", "b.mp4"}


async def test_re_registering_a_key_replaces_the_previous_provider():
    registry = PathLockRegistry()
    first = _StubProvider({"a.mp4"})
    registry.register("copies", first)
    registry.register("copies", _StubProvider({"b.mp4"}))

    result = await registry.locked_paths(["a.mp4", "b.mp4"])

    assert result == {"b.mp4"}
    assert first.calls == []


# -----------------------------------------------------------------------
# ---------- Not paying for an empty question ----------------------------
# -----------------------------------------------------------------------

async def test_asks_no_provider_when_the_path_set_is_empty():
    registry = PathLockRegistry()
    provider = _StubProvider({"a.mp4"})
    registry.register("stub", provider)

    assert await registry.locked_paths([]) == set()
    assert provider.calls == []


async def test_asks_no_provider_when_every_path_is_falsy():
    registry = PathLockRegistry()
    provider = _StubProvider({"a.mp4"})
    registry.register("stub", provider)

    assert await registry.locked_paths(["", None]) == set()
    assert provider.calls == []


# -----------------------------------------------------------------------
# ---------- Failing closed ----------------------------------------------
# -----------------------------------------------------------------------

async def test_propagates_a_provider_failure_instead_of_reporting_unlocked():
    """Returning an empty set on error would let a delete through on a file that is
    mid-migration. Silence here is data loss, not degraded service."""
    registry = PathLockRegistry()
    registry.register("broken", _FailingProvider())

    with pytest.raises(RuntimeError):
        await registry.locked_paths(["a.mp4"])


async def test_one_broken_provider_fails_the_whole_lookup():
    registry = PathLockRegistry()
    registry.register("healthy", _StubProvider({"a.mp4"}))
    registry.register("broken", _FailingProvider())

    with pytest.raises(RuntimeError):
        await registry.locked_paths(["a.mp4"])


# -----------------------------------------------------------------------
# ---------- Single-path convenience -------------------------------------
# -----------------------------------------------------------------------

async def test_reports_true_when_the_path_comes_back_locked():
    registry = PathLockRegistry()
    registry.register("stub", _StubProvider({"a.mp4"}))

    assert await registry.is_locked("a.mp4") is True


async def test_reports_false_when_the_path_does_not_come_back():
    registry = PathLockRegistry()
    registry.register("stub", _StubProvider(set()))

    assert await registry.is_locked("a.mp4") is False


# -----------------------------------------------------------------------
# ---------- Staying generic ---------------------------------------------
# -----------------------------------------------------------------------

#: Vocabulary that would mean the registry had learned about one particular feature.
FEATURE_VOCABULARY = (
    "migration",
    "source_path",
    "target_path",
    "renamed_target",
    "video",
    "conflict_strategy",
)


def test_the_module_names_no_feature_concept():
    """The registry exists so that catalog and browsing stop importing migration. If it
    grows migration vocabulary of its own, it has only moved the coupling."""
    source = PATH_LOCKS_SOURCE.read_text(encoding="utf-8").lower()

    found = [word for word in FEATURE_VOCABULARY if word in source]

    assert found == [], f"path_locks mentions feature-specific vocabulary: {found}"


def test_the_module_imports_no_feature():
    tree = ast.parse(PATH_LOCKS_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    leaked = sorted(name for name in imported if name.startswith("src.features"))

    assert leaked == [], f"path_locks imports features: {leaked}"
