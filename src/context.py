from dataclasses import dataclass
from enum import Enum
import strawberry
from typing import Annotated
from fastapi import Depends
from redis.asyncio import Redis
from src.config import Settings, get_settings

from src.config import Settings
from src.features.browsing.batch_operation_service import BatchOperationService
from src.features.browsing.browse_file_service import BrowseFileService
from src.features.catalog.catalog_service import CatalogService
from src.platform.cache.cache_service import CacheService
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.media.ffmpeg_service import FFmpegService
from src.features.migration.migration_service import MIGRATION_EXECUTOR_KEY, MigrationService
from src.features.migration.migration_task import MigrationTaskModel
from src.platform.jobs.dispatch import Queue, TaskDispatcher, open_dispatcher
from src.platform.jobs.path_locks import PathLockRegistry
from src.platform.jobs.progress_bus import ProgressBus, ProgressPublisher
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
    MIGRATION_DISPATCHER = TaskDispatcher
    PROGRESS_BUS = ProgressBus
    PROGRESS_PUBLISHER = ProgressPublisher

_cache_service: CacheService | None = None
_resource_handler_service: ResourceHandlerService | None = None
_ffmpeg_service: FFmpegService | None = None
_tag_operation_service: TagOperationService | None = None
_series_service: SeriesService | None = None
_migration_service: MigrationService | None = None
_task_infrastructure: "TaskInfrastructure | None" = None
_path_lock_registry: PathLockRegistry | None = None
_thumbnail_service: ThumbnailService | None = None

def get_cache_service(settings: Settings = Depends(get_settings)) -> CacheService | None:
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService(config=settings.cache_config)
    return _cache_service

def get_resource_handler_service(settings: Settings = Depends(get_settings)) -> ResourceHandlerService | None:
    global _resource_handler_service
    if _resource_handler_service is None:
        _resource_handler_service = ResourceHandlerService(settings=settings)
    return _resource_handler_service
ResourceHandlerServiceDep = Annotated[ResourceHandlerService, Depends(get_resource_handler_service)]

def get_ffmpeg_service(settings: Settings = Depends(get_settings)) -> FFmpegService | None:
    global _ffmpeg_service
    if _ffmpeg_service is None:
        _ffmpeg_service = FFmpegService(semaphore_limit=settings.ffmpeg_semaphore_limit)
    return _ffmpeg_service
FFmpegServiceDep = Annotated[FFmpegService, Depends(get_ffmpeg_service)]

def get_tag_operation_service(settings: Settings = Depends(get_settings)) -> TagOperationService | None:
    global _tag_operation_service
    if _tag_operation_service is None:
        _tag_operation_service = TagOperationService(settings=settings)
    return _tag_operation_service

def get_series_service() -> SeriesService | None:
    global _series_service
    if _series_service is None:
        _series_service = SeriesService()
    return _series_service

def get_dir_metadata_service(
    settings: Settings = Depends(get_settings),
    resource_handler_service = Depends(get_resource_handler_service), 
    cache_service = Depends(get_cache_service)
) -> DirMetadataService | None:
    return DirMetadataService(
        settings=settings, 
        resource_handler_service=resource_handler_service, 
        cache_service=cache_service
    )

def get_thumbnail_service(
    resource_handler_service = Depends(get_resource_handler_service),
    ffmpeg = Depends(get_ffmpeg_service),
    settings: Settings = Depends(get_settings),
) -> ThumbnailService | None:
    # One per process: its storage breaker has to remember an outage across requests.
    global _thumbnail_service
    if _thumbnail_service is None:
        _thumbnail_service = ThumbnailService(
            settings=settings,
            resource_handler_service=resource_handler_service,
            ffmpeg_service=ffmpeg,
        )
    return _thumbnail_service
ThumbnailServiceDep = Annotated[ThumbnailService, Depends(get_thumbnail_service)]

def get_path_lock_registry(
    resource_handler_service = Depends(get_resource_handler_service),
    dir_metadata_service = Depends(get_dir_metadata_service),
    settings: Settings = Depends(get_settings),
) -> PathLockRegistry | None:
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
) -> BrowseFileService | None:
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
    series_service = Depends(get_series_service),
) -> BatchOperationService | None:
    return BatchOperationService(
        dir_metadata_service=dir_metadata_service,
        tag_operation_service=tag_operation_service,
        thumbnail_service=thumbnail_service,
        resource_handler_service=resource_handler_service,
        ffmpeg_service=ffmpeg_service,
        series_service=series_service,
    )

def get_catalog_service(
    settings: Settings = Depends(get_settings),
    tag_operation_service = Depends(get_tag_operation_service),
    dir_metadata_service = Depends(get_dir_metadata_service),
    resource_handler_service = Depends(get_resource_handler_service),
    ffmpeg_service = Depends(get_ffmpeg_service),
    path_locks = Depends(get_path_lock_registry),
    series_service = Depends(get_series_service),
) -> CatalogService | None:
    return CatalogService(
        settings=settings,
        tag_operation_service=tag_operation_service,
        dir_metadata_service=dir_metadata_service,
        resource_handler_service=resource_handler_service,
        ffmpeg_service=ffmpeg_service,
        path_locks=path_locks,
        series_service=series_service,
    )

def get_migration_service(
    resource_handler_service=Depends(get_resource_handler_service),
    dir_metadata_service=Depends(get_dir_metadata_service),
    settings: Settings = Depends(get_settings),
    series_service=Depends(get_series_service),
) -> MigrationService | None:
    global _migration_service
    if _migration_service is None:
        _migration_service = MigrationService(
            resource_handler_service=resource_handler_service,
            dir_metadata_service=dir_metadata_service,
            series_service=series_service,
            progress_flush_interval=settings.tasks.progress_flush_interval,
        )
    return _migration_service

@dataclass
class TaskInfrastructure:
    """
    What the web process needs to hand work to the workers and watch it progress.

    The web process runs no tasks. It puts task ids on the workers' queues and relays the
    progress frames the workers publish to the clients watching. It publishes a frame of
    its own only when it settles a task itself — a cancel of a task no worker has started.
    """

    redis: Redis
    migration_dispatcher: TaskDispatcher
    progress_bus: ProgressBus
    progress_publisher: ProgressPublisher

    async def shutdown(self) -> None:
        await self.progress_bus.stop()
        await self.migration_dispatcher.close()
        await self.redis.aclose()


async def init_task_infrastructure() -> TaskInfrastructure:
    """
    Connect the web process to the task queues and the progress channels. Called from the
    app lifespan, where Depends() is unavailable.
    """
    global _task_infrastructure
    settings = get_settings()
    prefix = settings.cache_config.key_prefix

    redis = Redis.from_url(settings.tasks.redis_url, decode_responses=True)
    dispatcher = await open_dispatcher(
        Queue.MIGRATION, settings.tasks.redis_url, prefix, MigrationTaskModel
    )
    bus = ProgressBus(redis, prefix, watchdog_interval=settings.tasks.observe_watchdog_interval)
    await bus.start()

    _task_infrastructure = TaskInfrastructure(
        redis=redis,
        migration_dispatcher=dispatcher,
        progress_bus=bus,
        progress_publisher=ProgressPublisher(redis, prefix),
    )
    return _task_infrastructure


def _require_task_infrastructure() -> TaskInfrastructure:
    if _task_infrastructure is None:
        raise RuntimeError("Task infrastructure is not running; init_task_infrastructure() was not called")
    return _task_infrastructure


def get_migration_dispatcher() -> TaskDispatcher:
    return _require_task_infrastructure().migration_dispatcher


def get_progress_bus() -> ProgressBus:
    return _require_task_infrastructure().progress_bus


def get_progress_publisher() -> ProgressPublisher:
    return _require_task_infrastructure().progress_publisher

def get_video_stream_service(
    resource_handler_service = Depends(get_resource_handler_service),
    ffmpeg_service = Depends(get_ffmpeg_service)
) -> VideoStreamService | None:
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
    migration_dispatcher: TaskDispatcher = Depends(get_migration_dispatcher),
    progress_bus: ProgressBus = Depends(get_progress_bus),
    progress_publisher: ProgressPublisher = Depends(get_progress_publisher),
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
        ContextEnum.MIGRATION_DISPATCHER: migration_dispatcher,
        ContextEnum.PROGRESS_BUS: progress_bus,
        ContextEnum.PROGRESS_PUBLISHER: progress_publisher,
    }

def get_context_value(info: strawberry.Info, key: ContextEnum):
    return info.context[key]