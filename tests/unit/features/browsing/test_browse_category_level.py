"""
Behaviour specification — the category level lists what is configured.

A row at the category level is a configured mount point, not something found by walking
a disk. It was nonetheless being put through the same zero-aggregate filter as a real
sub-directory, so a pseudo-name holding no video at all — a freshly mounted drive, an
empty S3 bucket — vanished, and the category looked broken rather than empty.

The filter still applies one level down, where a row really is a discovery: that is the
distinction these tests pin.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import config
from src.config import Settings
from src.features.browsing.browse_file_service import BrowseFileService, DirectoryEntry
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.cache.cache_service import CacheService
from src.platform.jobs.path_locks import PathLockRegistry
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit

CATEGORY = "Test-category"


@pytest.fixture
def empty_resource_dir(tmp_path: Path) -> Path:
    """A configured mount point that exists but holds nothing at all."""
    root = tmp_path / "empty_videos"
    root.mkdir()
    return root


@pytest.fixture
def two_mounts_settings(
    test_settings: Settings,
    local_resource_dir: Path,
    empty_resource_dir: Path,
    monkeypatch,
) -> Settings:
    """One category, two configured pseudo-names: one with videos, one with none."""
    payload = test_settings.model_dump()
    payload["resource_paths"] = {
        CATEGORY: {
            "Test-resource": str(local_resource_dir),
            "Empty-resource": str(empty_resource_dir),
        },
    }
    settings = Settings.model_validate(payload)
    monkeypatch.setattr(config, "_settings", settings)
    return settings


@pytest.fixture
def two_mounts_handler_service(two_mounts_settings: Settings) -> ResourceHandlerService:
    return ResourceHandlerService(settings=two_mounts_settings)


@pytest.fixture
def two_mounts_browse_svc(
    two_mounts_settings: Settings,
    two_mounts_handler_service: ResourceHandlerService,
    local_cache_service: CacheService,
) -> BrowseFileService:
    ffmpeg = MagicMock(spec=FFmpegService, name="FFmpegService")
    ffmpeg.get_video_duration = AsyncMock(return_value=120.0)
    return BrowseFileService(
        settings=two_mounts_settings,
        dir_metadata_service=DirMetadataService(
            settings=two_mounts_settings,
            resource_handler_service=two_mounts_handler_service,
            cache_service=local_cache_service,
        ),
        resource_handler_service=two_mounts_handler_service,
        ffmpegService=ffmpeg,
        path_locks=PathLockRegistry(),
    )


def _category_level(handler_svc: ResourceHandlerService) -> AbsolutePath:
    return AbsolutePath.from_existing_path(
        path=CATEGORY, category=CATEGORY, handler=handler_svc.get_handler(CATEGORY),
    )


def _entry_name(entry) -> str:
    """Display name of a listing row, whichever kind it is."""
    return entry.name if isinstance(entry, DirectoryEntry) else entry.document.name


def _directory_entry(nodes, name: str) -> DirectoryEntry | None:
    for node in nodes:
        if isinstance(node, DirectoryEntry) and node.name == name:
            return node
    return None


# -----------------------------------------------------------------------
# ------------------ Configured pseudo-names always list -----------------
# -----------------------------------------------------------------------

async def test_category_level_lists_a_configured_pseudo_name_holding_no_video(
    two_mounts_browse_svc, init_db, two_mounts_handler_service,
):
    nodes = await two_mounts_browse_svc.get_node_list_in_directory(
        _category_level(two_mounts_handler_service)
    )

    assert "Empty-resource" in [_entry_name(n) for n in nodes]


async def test_category_level_lists_every_configured_pseudo_name(
    two_mounts_browse_svc, init_db, two_mounts_handler_service,
):
    nodes = await two_mounts_browse_svc.get_node_list_in_directory(
        _category_level(two_mounts_handler_service)
    )

    assert sorted(_entry_name(n) for n in nodes) == ["Empty-resource", "Test-resource"]


async def test_an_empty_pseudo_name_reports_a_zero_aggregate(
    two_mounts_browse_svc, init_db, two_mounts_handler_service,
):
    nodes = await two_mounts_browse_svc.get_node_list_in_directory(
        _category_level(two_mounts_handler_service)
    )

    entry = _directory_entry(nodes, "Empty-resource")
    assert entry is not None
    assert entry.size == 0.0


# -----------------------------------------------------------------------
# ------------------ The level below keeps its filter --------------------
# -----------------------------------------------------------------------

async def test_a_sub_directory_holding_no_video_is_still_hidden(
    two_mounts_browse_svc, init_db, two_mounts_handler_service, local_resource_dir: Path,
):
    subdir = local_resource_dir / "subdir"
    assert (subdir / "empty").is_dir()

    nodes = await two_mounts_browse_svc.get_node_list_in_directory(
        AbsolutePath.from_existing_path(
            path=str(subdir).replace("\\", "/"),
            category=CATEGORY,
            handler=two_mounts_handler_service.get_handler(CATEGORY),
        )
    )

    assert "empty" not in [_entry_name(n) for n in nodes]
