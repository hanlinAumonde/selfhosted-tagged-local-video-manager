"""
Unit-test scaffolding shared across tests/unit/.

- Auto-applies the ``unit`` marker to every test under tests/unit/.
- Builds a real on-disk video tree under ``tmp_path`` for FS-touching tests.
- Provides a Settings override that points category Test-category/Test-resource
  at that real tree, so tests can mix real LocalFS handler behavior with the
  rest of the project's configuration.
"""

from pathlib import Path

import pytest

from src import config
from src.config import Settings
from src.platform.cache.cache_service import CacheService
from src.platform.storage.local_fs.local_fs_handler import LocalFSResourceHandler
from src.platform.storage.resource_handler_service import ResourceHandlerService


# -----------------------------------------------------------------------
# ----------------------- Auto-apply unit mark ---------------------------
# -----------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/unit" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.unit)


# -----------------------------------------------------------------------
# ------------------------ On-disk fixture tree --------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def local_resource_dir(tmp_path: Path) -> Path:
    """Build a fake video tree under ``tmp_path`` and return its root path.

    Layout::

        <root>/
          movie_a.mp4         # 100 bytes
          movie_b.mp4         # 200 bytes
          subdir/
            movie_c.mp4       # 300 bytes
            empty/            # empty directory
          notes.txt           # not a video file
    """
    root = tmp_path / "videos"
    root.mkdir()
    (root / "movie_a.mp4").write_bytes(b"a" * 100)
    (root / "movie_b.mp4").write_bytes(b"b" * 200)
    sub = root / "subdir"
    sub.mkdir()
    (sub / "movie_c.mp4").write_bytes(b"c" * 300)
    (sub / "empty").mkdir()
    (root / "notes.txt").write_text("not a video")
    return root


# -----------------------------------------------------------------------
# ------------------------ Settings overrides ----------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def fs_settings(test_settings: Settings, local_resource_dir: Path, monkeypatch) -> Settings:
    """Clone of test_settings whose Test-resource pseudo-name points at the on-disk fake tree.

    Also overrides ``config._settings`` so any code path that reads it sees the
    real-FS path while the test runs.
    """
    payload = test_settings.model_dump()
    payload["resource_paths"] = {
        "Test-category": {"Test-resource": str(local_resource_dir)},
    }
    settings = Settings.model_validate(payload)
    monkeypatch.setattr(config, "_settings", settings)
    return settings


# -----------------------------------------------------------------------
# ------------------------ LocalFS handler -------------------------------
# -----------------------------------------------------------------------

@pytest.fixture
def local_handler(fs_settings: Settings, local_resource_dir: Path) -> LocalFSResourceHandler:
    """A LocalFSResourceHandler bound to the on-disk fake tree (no ROOT_PATH)."""
    return LocalFSResourceHandler(
        category="Test-category",
        pseudo_paths={"Test-resource": str(local_resource_dir)},
        root_path=None,
    )


# -----------------------------------------------------------------------
# ---------------------- Composite service fixtures ----------------------
# -----------------------------------------------------------------------

@pytest.fixture
def local_resource_handler_service(fs_settings: Settings) -> ResourceHandlerService:
    """A ResourceHandlerService backed by the real on-disk fake tree."""
    return ResourceHandlerService(settings=fs_settings)


@pytest.fixture
def local_cache_service(fs_settings: Settings) -> CacheService:
    """An in-memory CacheService for unit tests."""
    return CacheService(config=fs_settings.cache_config)


# -----------------------------------------------------------------------
# ------------------------ Two-category variants -------------------------
# -----------------------------------------------------------------------
# The single-category fixtures above answer "one real directory on disk".
# These answer "two of them, in different categories" — what any test that moves
# or compares across category boundaries needs. Nothing here is task-specific.

@pytest.fixture
def target_dir(tmp_path: Path) -> Path:
    """A second real directory, separate from ``local_resource_dir``."""
    d = tmp_path / "target"
    d.mkdir()
    return d


@pytest.fixture
def two_category_settings(
    test_settings: Settings,
    local_resource_dir: Path,
    target_dir: Path,
    monkeypatch,
) -> Settings:
    """Settings with two categories: source and target, pointing at real dirs."""
    payload = test_settings.model_dump()
    payload["resource_paths"] = {
        "Test-category": {"Test-resource": str(local_resource_dir)},
        "Target-category": {"Target-resource": str(target_dir)},
    }
    settings = Settings.model_validate(payload)
    monkeypatch.setattr(config, "_settings", settings)
    return settings


@pytest.fixture
def two_cat_handler_service(two_category_settings: Settings) -> ResourceHandlerService:
    return ResourceHandlerService(settings=two_category_settings)


@pytest.fixture
def two_cat_cache_service(two_category_settings: Settings) -> CacheService:
    return CacheService(config=two_category_settings.cache_config)
