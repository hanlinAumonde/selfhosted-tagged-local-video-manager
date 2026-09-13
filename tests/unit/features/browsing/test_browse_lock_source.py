"""
Where BrowseFileService gets its lock answers from.

The behaviour driven by those answers is pinned by test_browse_migration_targets.py, which
goes through real migration documents. What is pinned here is that the answer arrives
through the injected registry — so a directory listing can be tested with no migration in
sight, and a second kind of job can hold a file without browsing learning about it.
"""

import ast
from pathlib import Path

import pytest

from src.config import Settings
from src.features.browsing.browse_file_service import (
    BrowseFileService, DirectoryEntry, VideoEntry,
)
from src.features.catalog.video import VideoModel
from src.features.migration.migration_task import MigrationTaskModel
from src.platform.storage.absolute_path import AbsolutePath

pytestmark = pytest.mark.unit

BROWSE_SOURCE = (
    Path(__file__).resolve().parents[4]
    / "src" / "features" / "browsing" / "browse_file_service.py"
)


class _StubRegistry:
    """Stands in for PathLockRegistry, reporting a fixed set and counting the asks."""

    def __init__(self, locked: set[str] | None = None):
        self._locked = locked or set()
        self.calls: list[set[str]] = []

    async def locked_paths(self, db_paths) -> set[str]:
        wanted = set(db_paths)
        self.calls.append(wanted)
        return self._locked & wanted


@pytest.fixture
def browse_svc_factory(
    fs_settings: Settings, dir_meta_svc, local_resource_handler_service, ffmpeg_svc,
):
    """Build a browse service around a given lock registry."""
    def _build(registry) -> BrowseFileService:
        return BrowseFileService(
            settings=fs_settings,
            dir_metadata_service=dir_meta_svc,
            resource_handler_service=local_resource_handler_service,
            ffmpegService=ffmpeg_svc,
            path_locks=registry,
        )
    return _build


def _entry_name(entry) -> str:
    return entry.name if isinstance(entry, DirectoryEntry) else entry.document.name


def _db_path(handler, file_path: Path) -> str:
    return handler.convert_to_DB_format_path(str(file_path).replace("\\", "/"))


def _abs_path(handler, directory: Path) -> AbsolutePath:
    return AbsolutePath.from_existing_path(
        path=str(directory).replace("\\", "/"),
        category="Test-category",
        handler=handler,
    )


def _video_entry(nodes, name: str) -> VideoEntry | None:
    for node in nodes:
        if isinstance(node, VideoEntry) and node.document.name == name:
            return node
    return None


# -----------------------------------------------------------------------
# ---------- Listings are marked from the registry -----------------------
# -----------------------------------------------------------------------

async def test_marks_a_row_locked_when_the_registry_reports_its_path(
    browse_svc_factory, init_db, video_factory,
    local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    db_path = _db_path(handler, local_resource_dir / "movie_a.mp4")
    await video_factory(name="movie_a", path=db_path)
    svc = browse_svc_factory(_StubRegistry({db_path}))

    nodes = await svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    entry = _video_entry(nodes, "movie_a")
    assert entry is not None
    assert entry.is_locked is True
    # No migration document exists: the lock came from the registry alone.
    assert await MigrationTaskModel.find({}).count() == 0


async def test_skips_a_locked_path_that_has_no_document(
    browse_svc_factory, init_db, local_resource_handler_service, local_resource_dir,
):
    """The half-written destination rule, now stated for any kind of job rather than for
    migration specifically."""
    handler = local_resource_handler_service.get_handler("Test-category")
    db_path = _db_path(handler, local_resource_dir / "movie_a.mp4")
    svc = browse_svc_factory(_StubRegistry({db_path}))

    nodes = await svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    assert await VideoModel.find_one({"path": db_path}) is None
    assert "movie_a" not in [_entry_name(n) for n in nodes]


async def test_leaves_every_row_unlocked_when_the_registry_reports_nothing(
    browse_svc_factory, init_db, local_resource_handler_service, local_resource_dir,
):
    handler = local_resource_handler_service.get_handler("Test-category")
    svc = browse_svc_factory(_StubRegistry())

    nodes = await svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    videos = [n for n in nodes if isinstance(n, VideoEntry)]
    assert videos != []
    assert all(entry.is_locked is False for entry in videos)


async def test_asks_the_registry_once_for_the_whole_directory(
    browse_svc_factory, init_db, local_resource_handler_service, local_resource_dir,
):
    """Bulk is the point: a listing costs one question, not one per row."""
    handler = local_resource_handler_service.get_handler("Test-category")
    registry = _StubRegistry()
    svc = browse_svc_factory(registry)

    await svc.get_node_list_in_directory(_abs_path(handler, local_resource_dir))

    assert len(registry.calls) == 1
    assert _db_path(handler, local_resource_dir / "movie_a.mp4") in registry.calls[0]


# -----------------------------------------------------------------------
# ---------- The import this refactor exists to remove -------------------
# -----------------------------------------------------------------------

def test_the_module_does_not_import_the_migration_feature():
    tree = ast.parse(BROWSE_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    leaked = sorted(n for n in imported if n.startswith("src.features.migration"))

    assert leaked == [], f"browse_file_service still imports migration: {leaked}"
