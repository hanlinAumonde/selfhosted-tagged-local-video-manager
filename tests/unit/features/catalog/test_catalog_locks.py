"""
Where CatalogService gets its lock answers from.

CatalogService is already the facade the resolvers call for lock state, so its published
behaviour must not shift — only its source of truth does. Every lock fact below is
produced by a stub registry, with no migration document anywhere.
"""

import ast
from pathlib import Path

import pytest

from src.errors import InputValidationError
from src.features.catalog.catalog_service import VideoSearchCriteria
from src.schema.types.pydantic_types.video_type import UpdateVideoMetadataInputModel

pytestmark = pytest.mark.unit

CATALOG_SOURCE = (
    Path(__file__).resolve().parents[4]
    / "src" / "features" / "catalog" / "catalog_service.py"
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

    async def is_locked(self, db_path: str) -> bool:
        return db_path in await self.locked_paths([db_path])


def _criteria(**kwargs) -> VideoSearchCriteria:
    return VideoSearchCriteria(page_number=1, page_size=10, **kwargs)


# -----------------------------------------------------------------------
# ---------- A search page carries its own lock state --------------------
# -----------------------------------------------------------------------

async def test_fills_locked_paths_from_the_registry(
    catalog_svc_factory, init_db, video_factory,
):
    video = await video_factory(name="locked_one")
    svc = catalog_svc_factory(_StubRegistry({video.path}))

    page = await svc.search_videos(_criteria())

    assert page.locked_paths == {video.path}


async def test_leaves_locked_paths_empty_when_nothing_is_held(
    catalog_svc_factory, init_db, video_factory,
):
    await video_factory(name="free_one")
    svc = catalog_svc_factory(_StubRegistry())

    page = await svc.search_videos(_criteria())

    assert page.videos != []
    assert page.locked_paths == set()


async def test_asks_the_registry_once_per_page(
    catalog_svc_factory, init_db, video_factory,
):
    """The reason the page carries a set instead of each row carrying a flag."""
    for i in range(5):
        await video_factory(name=f"v{i}")
    registry = _StubRegistry()
    svc = catalog_svc_factory(registry)

    await svc.search_videos(_criteria())

    assert len(registry.calls) == 1
    assert len(registry.calls[0]) == 5


# -----------------------------------------------------------------------
# ---------- Single and bulk lock lookups --------------------------------
# -----------------------------------------------------------------------

async def test_is_locked_reports_true_for_a_held_path(catalog_svc_factory, init_db):
    svc = catalog_svc_factory(_StubRegistry({"Test-category/Test-resource/a.mp4"}))

    assert await svc.is_locked("Test-category/Test-resource/a.mp4") is True


async def test_is_locked_reports_false_for_a_free_path(catalog_svc_factory, init_db):
    svc = catalog_svc_factory(_StubRegistry())

    assert await svc.is_locked("Test-category/Test-resource/a.mp4") is False


async def test_locked_paths_returns_the_held_subset(catalog_svc_factory, init_db):
    svc = catalog_svc_factory(_StubRegistry({"a.mp4"}))

    assert await svc.locked_paths(["a.mp4", "b.mp4"]) == {"a.mp4"}


# -----------------------------------------------------------------------
# ---------- Write guards still refuse a held file -----------------------
# -----------------------------------------------------------------------

async def test_update_metadata_refuses_a_locked_video(
    catalog_svc_factory, init_db, video_factory,
):
    video = await video_factory(name="locked_one")
    svc = catalog_svc_factory(_StubRegistry({video.path}))

    with pytest.raises(InputValidationError):
        await svc.update_metadata(
            UpdateVideoMetadataInputModel(videoId=str(video.id), tags=[])
        )


async def test_delete_video_refuses_a_locked_video(
    catalog_svc_factory, init_db, video_factory,
):
    video = await video_factory(name="locked_one")
    svc = catalog_svc_factory(_StubRegistry({video.path}))

    with pytest.raises(InputValidationError):
        await svc.delete_video(str(video.id))


async def test_delete_video_proceeds_when_the_registry_reports_nothing(
    catalog_svc_factory, init_db, video_factory, local_resource_dir,
):
    """The guard must not become a blanket refusal."""
    video = await video_factory(
        name="movie_a", path="Test-category/Test-resource/movie_a.mp4"
    )
    svc = catalog_svc_factory(_StubRegistry())

    await svc.delete_video(str(video.id))

    from src.features.catalog.video import VideoModel
    assert await VideoModel.get(video.id) is None


async def test_assert_videos_unlocked_refuses_the_whole_batch(
    catalog_svc_factory, init_db, video_factory,
):
    """A batch either starts clean or does not start."""
    free = await video_factory(name="free_one")
    held = await video_factory(name="held_one")
    svc = catalog_svc_factory(_StubRegistry({held.path}))

    with pytest.raises(InputValidationError):
        await svc.assert_videos_unlocked([str(free.id), str(held.id)])


async def test_assert_videos_unlocked_passes_a_clean_batch(
    catalog_svc_factory, init_db, video_factory,
):
    a = await video_factory(name="a")
    b = await video_factory(name="b")
    svc = catalog_svc_factory(_StubRegistry())

    await svc.assert_videos_unlocked([str(a.id), str(b.id)])


# -----------------------------------------------------------------------
# ---------- The import this refactor exists to remove -------------------
# -----------------------------------------------------------------------

def test_the_module_does_not_import_the_migration_feature():
    tree = ast.parse(CATALOG_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    leaked = sorted(n for n in imported if n.startswith("src.features.migration"))

    assert leaked == [], f"catalog_service still imports migration: {leaked}"
