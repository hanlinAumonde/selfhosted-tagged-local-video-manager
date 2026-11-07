"""
Assembly root of the migration worker process.

Run exactly one of these processes per queue — recovery relies on it (see
``TaskStateMachine.plan_recovery``)::

    taskiq worker src.worker:create_broker --workers 1 --ack-type when_received \
        --max-async-tasks 16

``--max-async-tasks`` is not the concurrency limit: tasks waiting for a copy slot also
occupy one, so it must stay well above ``tasks.max_concurrent`` or tasks for an idle
disk queue up behind tasks waiting for a busy one. The real limits are ``DeviceSlots``.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress

from redis.asyncio import Redis
from taskiq import AsyncBroker, TaskiqEvents, TaskiqState

from src.config import Settings, init_settings
from src.db.setup_mongo import setup_mongo
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.features.catalog.series_service import SeriesService
from src.features.migration.device_slots import DeviceSlots
from src.features.migration.migration_service import MigrationService
from src.features.migration.migration_task import MigrationTaskModel
from src.logger import get_logger, setup_logger
from src.platform.cache.cache_service import CacheService
from src.platform.jobs.dispatch import RUN_TASK, Queue, TaskDispatcher, build_broker
from src.platform.jobs.progress_bus import ProgressPublisher
from src.platform.storage.resource_handler_service import ResourceHandlerService

logger = get_logger("worker")


class MigrationWorker:
    """
    Everything the migration worker process holds: the service that runs migrations, the
    publisher their frames go out through, and the dispatcher that keeps the queue whole.
    """

    def __init__(self, settings: Settings, broker: AsyncBroker, redis: Redis):
        """
        :param settings: Application settings.
        :type settings: Settings
        :param broker: The migration queue's broker, used to re-send recovered tasks.
        :type broker: AsyncBroker
        :param redis: Client for publishing progress.
        :type redis: Redis
        """
        handler_service = ResourceHandlerService(settings=settings)
        self.cache_service = CacheService(config=settings.cache_config)
        self.service = MigrationService(
            resource_handler_service=handler_service,
            dir_metadata_service=DirMetadataService(
                settings=settings,
                resource_handler_service=handler_service,
                cache_service=self.cache_service,
            ),
            series_service=SeriesService(),
            progress_flush_interval=settings.tasks.progress_flush_interval,
            copy_slots=DeviceSlots.from_settings(settings),
        )
        self.publisher = ProgressPublisher(redis, settings.cache_config.key_prefix)
        self.dispatcher = TaskDispatcher(broker, MigrationTaskModel)
        self._reconcile_interval = settings.tasks.reconcile_interval
        self._reconciler: asyncio.Task | None = None

    async def run(self, task_id: str) -> None:
        """
        The job behind every message on the migration queue.

        :param task_id: String form of the task's ObjectId.
        :type task_id: str
        :rtype: None
        """
        await self.publisher.relay(self.service.run_task(task_id))

    async def start(self) -> None:
        """
        Re-queue what the previous run of this worker left behind, then keep reconciling.

        :rtype: None
        """
        await self.dispatcher.recover(self.service)
        self._reconciler = asyncio.create_task(self._reconcile_forever(), name="reconcile")

    async def stop(self) -> None:
        if self._reconciler is not None:
            self._reconciler.cancel()
            with suppress(asyncio.CancelledError):
                await self._reconciler
            self._reconciler = None
        await self.cache_service.close()

    async def _reconcile_forever(self) -> None:
        # Covers a Redis restart that loses messages while this worker keeps running; a
        # failed pass is retried on the next tick rather than ending the loop.
        while True:
            await asyncio.sleep(self._reconcile_interval)
            try:
                await self.dispatcher.reconcile(stale_after=self._reconcile_interval)
            except Exception as e:
                logger.warning(f"Reconciliation pass failed: {e}")


def create_broker() -> AsyncBroker:
    """
    Build the migration queue's broker with the worker wired onto it.

    A factory rather than a module-level broker, so importing this module does not load
    the configuration; the taskiq CLI calls it when given ``src.worker:create_broker``.

    :return: The broker the taskiq worker should listen on.
    :rtype: AsyncBroker
    """
    settings = init_settings()
    broker = build_broker(
        Queue.MIGRATION, settings.tasks.redis_url, settings.cache_config.key_prefix
    )

    async def run_task(task_id: str) -> None:
        await broker.state.migration_worker.run(task_id)

    broker.register_task(run_task, task_name=RUN_TASK)

    @broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def startup(state: TaskiqState) -> None:
        setup_logger(
            log_dir=settings.logging.log_dir,
            rotation=settings.logging.rotation,
            retention=settings.logging.retention,
        )
        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(max_workers=settings.io_thread_pool_size, thread_name_prefix="storage-io")
        )
        await setup_mongo(settings.mongo)
        state.redis = Redis.from_url(settings.tasks.redis_url, decode_responses=True)
        state.migration_worker = MigrationWorker(settings, broker, state.redis)
        await state.migration_worker.start()
        logger.info("Migration worker started")

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def shutdown(state: TaskiqState) -> None:
        await state.migration_worker.stop()
        await state.redis.aclose()
        logger.info("Migration worker stopped")

    return broker
