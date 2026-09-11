from enum import Enum
import strawberry
from typing_extensions import Annotated
from fastapi import Depends
from src.config import Settings, get_settings

from src.config import Settings
from src.features.browsing.batch_operation_service import BatchOperationService
from src.features.browsing.browse_file_service import BrowseFileService
from src.features.catalog.catalog_service import CatalogService
from src.platform.cache.cache_service import CacheService
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.media.ffmpeg_service import FFmpegService
from src.features.migration.migration_service import MIGRATION_EXECUTOR_KEY, MigrationService
from src.platform.jobs.path_locks import PathLockRegistry
from src.platform.jobs.task_runner import TaskRunner
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.features.catalog.series_service import SeriesService
from src.features.catalog.tag_operation_service import TagOperationService
from src.features.playback.thumbnail_service import ThumbnailService
from src.features.playback.video_stream_service import VideoStreamService

class ContextEnum(Enum):
    SETTINGS = Settings
    CACHE_SERVICE = CacheService
    RESOURCE_HANDLER_SERVICE = ResourceHandlerService
    FFMPEG_SERVICE = FFmpegService
    THUMBNAIL_SERVICE = ThumbnailService
    TAG_OPERATION_SERVICE = TagOperationService
    SERIES_SERVICE = SeriesService
    DIR_METADATA_SERVICE = DirMetadataService
    BROWSE_FILE_SERVICE = BrowseFileService
    CATALOG_SERVICE = CatalogService
    BATCH_OPERATION_SERVICE = BatchOperationService
    MIGRATION_SERVICE = MigrationService
    TASK_RUNNER = TaskRunner

_cache_service: CacheService | None = None
_resource_handler_service: ResourceHandlerService | None = None
_ffmpeg_service: FFmpegService | None = None
_tag_operation_service: TagOperationService | None = None
_series_service: SeriesService | None = None
_migration_service: MigrationService | None = None
_task_runner: TaskRunner | None = None
_path_lock_registry: PathLockRegistry | None = None

def get_cache_service(settings: Settings = Depends(get_settings)):
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService(config=settings.cache_config)
    return _cache_service

def get_resource_handler_service(settings: Settings = Depends(get_settings)):
    global _resource_handler_service
    if _resource_handler_service is None:
        _resource_handler_service = ResourceHandlerService(settings=settings)
    return _resource_handler_service
ResourceHandlerServiceDep = Annotated[ResourceHandlerService, Depends(get_resource_handler_service)]

def get_ffmpeg_service(settings: Settings = Depends(get_settings)):
    global _ffmpeg_service
    if _ffmpeg_service is None:
        _ffmpeg_service = FFmpegService(semaphore_limit=settings.ffmpeg_semaphore_limit)
    return _ffmpeg_service
FFmpegServiceDep = Annotated[FFmpegService, Depends(get_ffmpeg_service)]

def get_tag_operation_service(settings: Settings = Depends(get_settings)):
    global _tag_operation_service
    if _tag_operation_service is None:
        _tag_operation_service = TagOperationService(settings=settings)
    return _tag_operation_service

def get_series_service():
    global _series_service
    if _series_service is None:
        _series_service = SeriesService()
    return _series_service

def get_dir_metadata_service(
    settings: Settings = Depends(get_settings),
    resource_handler_service = Depends(get_resource_handler_service), 
    cache_service = Depends(get_cache_service)
):
    return DirMetadataService(
        settings=settings, 
        resource_handler_service=resource_handler_service, 
        cache_service=cache_service
    )
# DirMetadataServiceDep = Annotated[DirMetadataService, Depends(get_dir_metadata_service)]

def get_thumbnail_service(
    resource_handler_service = Depends(get_resource_handler_service), 
    ffmpeg = Depends(get_ffmpeg_service),
    settings: Settings = Depends(get_settings)
):
    return ThumbnailService(
        settings=settings,
        resource_handler_service=resource_handler_service, 
        ffmpeg_service=ffmpeg
    )
ThumbnailServiceDep = Annotated[ThumbnailService, Depends(get_thumbnail_service)]

def get_path_lock_registry(
    resource_handler_service = Depends(get_resource_handler_service),
    dir_metadata_service = Depends(get_dir_metadata_service),
    settings: Settings = Depends(get_settings),
):
    """
    The registry that tells readers whether a file is spoken for by unfinished work.

    Wiring it up is this module's job precisely because it is the only place allowed to
    know both sides: the features that hold paths, and the features that display them.
    Registration happens here rather than at startup so the registry is never handed out
    half-built — an empty one would silently report every file as free.
    """
    global _path_lock_registry
    if _path_lock_registry is None:
        registry = PathLockRegistry()
        registry.register(
            MIGRATION_EXECUTOR_KEY,
            get_migration_service(
                resource_handler_service, dir_metadata_service, settings
            ),
        )
        _path_lock_registry = registry
    return _path_lock_registry

def get_browse_file_service(
    settings: Settings = Depends(get_settings),
    dir_metadata_service = Depends(get_dir_metadata_service), 
    resource_handler_service = Depends(get_resource_handler_service),
    ffmpeg_service = Depends(get_ffmpeg_service),
    path_locks = Depends(get_path_lock_registry)
):
    return BrowseFileService(
        settings=settings,
        dir_metadata_service=dir_metadata_service,
        resource_handler_service=resource_handler_service,
        ffmpegService=ffmpeg_service,
        path_locks=path_locks
    )
# BrowseFileServiceDep = Annotated[BrowseFileService, Depends(get_browse_file_service)]

def get_batch_operation_service(
    dir_metadata_service = Depends(get_dir_metadata_service),
    tag_operation_service = Depends(get_tag_operation_service),
    thumbnail_service = Depends(get_thumbnail_service),
    resource_handler_service = Depends(get_resource_handler_service),
    ffmpeg_service = Depends(get_ffmpeg_service),
):
    return BatchOperationService(
        dir_metadata_service=dir_metadata_service,
        tag_operation_service=tag_operation_service,
        thumbnail_service=thumbnail_service,
        resource_handler_service=resource_handler_service,
        ffmpeg_service=ffmpeg_service,
    )

def get_catalog_service(
    settings: Settings = Depends(get_settings),
    tag_operation_service = Depends(get_tag_operation_service),
    dir_metadata_service = Depends(get_dir_metadata_service),
    resource_handler_service = Depends(get_resource_handler_service),
    ffmpeg_service = Depends(get_ffmpeg_service),
    path_locks = Depends(get_path_lock_registry),
):
    return CatalogService(
        settings=settings,
        tag_operation_service=tag_operation_service,
        dir_metadata_service=dir_metadata_service,
        resource_handler_service=resource_handler_service,
        ffmpeg_service=ffmpeg_service,
        path_locks=path_locks,
    )

def get_migration_service(
    resource_handler_service=Depends(get_resource_handler_service),
    dir_metadata_service=Depends(get_dir_metadata_service),
    settings: Settings = Depends(get_settings),
):
    global _migration_service
    if _migration_service is None:
        _migration_service = MigrationService(
            resource_handler_service=resource_handler_service,
            dir_metadata_service=dir_metadata_service,
            progress_flush_interval=settings.tasks.progress_flush_interval,
        )
    return _migration_service

def get_task_runner(settings: Settings = Depends(get_settings)):
    global _task_runner
    if _task_runner is None:
        _task_runner = TaskRunner(max_concurrent=settings.tasks.max_concurrent)
    return _task_runner

async def init_task_runner() -> TaskRunner:
    """
    Build the runner and its executors eagerly at startup. Called from the app lifespan,
    where the Depends() machinery is not available, so the dependency chain is resolved
    by hand — the module-level singletons make later request-scoped lookups return these
    same instances.
    """
    settings = get_settings()
    resource_handler_service = get_resource_handler_service(settings)
    cache_service = get_cache_service(settings)
    dir_metadata_service = get_dir_metadata_service(
        settings, resource_handler_service, cache_service
    )
    migration_service = get_migration_service(
        resource_handler_service, dir_metadata_service, settings
    )

    runner = get_task_runner(settings)
    runner.register_executor(MIGRATION_EXECUTOR_KEY, migration_service)
    runner.start()
    await runner.recover()
    return runner

def get_video_stream_service(
    resource_handler_service = Depends(get_resource_handler_service),
    ffmpeg_service = Depends(get_ffmpeg_service)
):
    return VideoStreamService(
        resourceHandlerService=resource_handler_service, 
        ffmpegService=ffmpeg_service
    )
VideoStreamServiceDep = Annotated[VideoStreamService, Depends(get_video_stream_service)]

async def get_context(
    settings: Settings = Depends(get_settings),
    cache_service: CacheService = Depends(get_cache_service),
    resource_handler_service: ResourceHandlerService = Depends(get_resource_handler_service),
    ffmpeg_service: FFmpegService = Depends(get_ffmpeg_service),
    thumbnail_service: ThumbnailService = Depends(get_thumbnail_service),
    tag_operation_service: TagOperationService = Depends(get_tag_operation_service),
    series_service: SeriesService = Depends(get_series_service),
    dir_metadata_service: DirMetadataService = Depends(get_dir_metadata_service),
    browse_file_service: BrowseFileService = Depends(get_browse_file_service),
    batch_operation_service: BatchOperationService = Depends(get_batch_operation_service),
    catalog_service: CatalogService = Depends(get_catalog_service),
    migration_service: MigrationService = Depends(get_migration_service),
    task_runner: TaskRunner = Depends(get_task_runner),
):
    return {
        ContextEnum.SETTINGS: settings,
        ContextEnum.CACHE_SERVICE: cache_service,
        ContextEnum.RESOURCE_HANDLER_SERVICE: resource_handler_service,
        ContextEnum.FFMPEG_SERVICE: ffmpeg_service,
        ContextEnum.THUMBNAIL_SERVICE: thumbnail_service,
        ContextEnum.TAG_OPERATION_SERVICE: tag_operation_service,
        ContextEnum.SERIES_SERVICE: series_service,
        ContextEnum.DIR_METADATA_SERVICE: dir_metadata_service,
        ContextEnum.BROWSE_FILE_SERVICE: browse_file_service,
        ContextEnum.BATCH_OPERATION_SERVICE: batch_operation_service,
        ContextEnum.CATALOG_SERVICE: catalog_service,
        ContextEnum.MIGRATION_SERVICE: migration_service,
        ContextEnum.TASK_RUNNER: task_runner,
    }

def get_context_value(info: strawberry.Info, key: ContextEnum):
    return info.context[key]