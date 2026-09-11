"""
The path-lock wiring in the composition root.

An empty registry is the one failure that reports success: every file comes back unlocked,
the mutation guards wave everything through, and nothing raises. So the wiring that fills
it is pinned here rather than trusted.
"""

import pytest

from src import context
from src.config import Settings
from src.context import (
    get_catalog_service, get_browse_file_service, get_path_lock_registry,
)
from src.platform.jobs.path_locks import PathLockRegistry
from src.platform.jobs.task_model import TaskStatus
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def fresh_singletons(monkeypatch):
    """Each test resolves the wiring from scratch, as a new process would."""
    monkeypatch.setattr(context, "_path_lock_registry", None)
    monkeypatch.setattr(context, "_migration_service", None)


@pytest.fixture
def resolved_registry(
    fs_settings: Settings,
    local_resource_handler_service: ResourceHandlerService,
    dir_metadata_service_for_context,
) -> PathLockRegistry:
    return get_path_lock_registry(
        local_resource_handler_service, dir_metadata_service_for_context, fs_settings
    )


@pytest.fixture
def dir_metadata_service_for_context(fs_settings, local_resource_handler_service, local_cache_service):
    from src.features.browsing.dir_metadata_service import DirMetadataService
    return DirMetadataService(
        settings=fs_settings,
        resource_handler_service=local_resource_handler_service,
        cache_service=local_cache_service,
    )


async def test_the_registry_reports_a_path_a_migration_holds(
    resolved_registry, init_db, task_factory,
):
    """No task runner has been started, yet the registry must already answer — this is
    what an empty one would get wrong while raising nothing."""
    await task_factory(source_path="cat/res/a.mp4", status=TaskStatus.PROCESSING)

    assert await resolved_registry.is_locked("cat/res/a.mp4") is True


async def test_the_registry_reports_an_untouched_path_as_free(
    resolved_registry, init_db, task_factory,
):
    await task_factory(source_path="cat/res/a.mp4", status=TaskStatus.PROCESSING)

    assert await resolved_registry.is_locked("cat/res/free.mp4") is False


def test_the_registry_is_the_same_instance_on_every_request(
    fs_settings, local_resource_handler_service, dir_metadata_service_for_context,
):
    first = get_path_lock_registry(
        local_resource_handler_service, dir_metadata_service_for_context, fs_settings
    )
    second = get_path_lock_registry(
        local_resource_handler_service, dir_metadata_service_for_context, fs_settings
    )

    assert first is second


def test_the_services_that_read_locks_receive_that_registry(
    fs_settings, local_resource_handler_service, local_cache_service,
    dir_metadata_service_for_context, resolved_registry,
):
    """Both readers must share the root's registry rather than a private empty one."""
    from src.features.catalog.tag_operation_service import TagOperationService

    ffmpeg = FFmpegService(semaphore_limit=1)

    catalog = get_catalog_service(
        fs_settings,
        TagOperationService(settings=fs_settings),
        dir_metadata_service_for_context,
        local_resource_handler_service,
        ffmpeg,
        resolved_registry,
    )
    browse = get_browse_file_service(
        fs_settings,
        dir_metadata_service_for_context,
        local_resource_handler_service,
        ffmpeg,
        resolved_registry,
    )

    assert catalog.pathLocks is resolved_registry
    assert browse.pathLocks is resolved_registry
