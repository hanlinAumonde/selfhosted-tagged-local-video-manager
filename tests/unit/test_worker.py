"""The migration worker's assembly root, and the web process no longer running tasks."""

import asyncio
import json

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from taskiq import InMemoryBroker

from src import context as context_module
from src.config import Settings
from src.features.migration.device_slots import Device
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus
from src.platform.jobs.dispatch import RUN_TASK
from src.worker import MigrationWorker

pytestmark = pytest.mark.unit

SOURCE_DB = "Test-category/Test-resource/movie_a.mp4"
TARGET_DB = "Target-category/Target-resource/movie_a.mp4"


class _RecordingBroker(InMemoryBroker):
    def __init__(self):
        super().__init__(await_inplace=True)
        self.delivered: list[str] = []

        async def run_task(task_id: str) -> None:
            self.delivered.append(task_id)

        self.register_task(run_task, task_name=RUN_TASK)


@pytest.fixture
def worker_settings(two_category_settings: Settings, redis_url: str, monkeypatch) -> Settings:
    payload = two_category_settings.model_dump()
    payload["tasks"]["redis_url"] = redis_url
    payload["cache_config"]["key_prefix"] = "worker-test"
    settings = Settings.model_validate(payload)
    monkeypatch.setattr("src.config._settings", settings)
    return settings


@pytest_asyncio.fixture
async def redis(redis_url):
    client = Redis.from_url(redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def worker_factory(worker_settings, redis, init_db):
    workers: list[MigrationWorker] = []

    def _create(settings: Settings = worker_settings, broker=None) -> MigrationWorker:
        worker = MigrationWorker(settings, broker or _RecordingBroker(), redis)
        workers.append(worker)
        return worker

    yield _create
    for worker in workers:
        await worker.stop()


class TestMigrationJob:
    async def test_job_runs_the_task_and_publishes_its_frames(
        self, worker_factory, redis, task_factory, video_factory, target_dir,
    ):
        # Given a PENDING migration task between two real directories
        await video_factory(name="movie_a", path=SOURCE_DB)
        task = await task_factory(source_path=SOURCE_DB, target_path=TARGET_DB, file_size=100)
        # And a worker built on an in-memory broker and the real Redis
        worker = worker_factory()

        # When the migration job is executed for that task id
        await worker.run(str(task.id))

        # Then the stored status is COMPLETED
        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.COMPLETED
        assert (target_dir / "movie_a.mp4").exists()
        # And the task's latest frame in Redis is COMPLETED
        latest = json.loads(await redis.get(f"worker-test:task:{task.id}:latest"))
        assert latest["status"] == "COMPLETED"


class TestWorkerStartup:
    async def test_startup_recovers_orphans_and_redelivers_pending_tasks(
        self, worker_factory, task_factory,
    ):
        # Given a migration task left in DB_UPDATED and a PENDING one
        orphan = await task_factory(status=TaskStatus.DB_UPDATED)
        pending = await task_factory(
            source_path="Test-category/Test-resource/movie_b.mp4",
            target_path="Target-category/Target-resource/movie_b.mp4",
        )
        broker = _RecordingBroker()
        worker = worker_factory(broker=broker)

        # When the worker's startup routine runs
        await worker.start()

        # Then both task ids are delivered to the migration queue
        assert sorted(broker.delivered) == sorted([str(orphan.id), str(pending.id)])
        # And the orphan is stored as PENDING with resume_from DELETING_SOURCE
        stored = await MigrationTaskModel.get(orphan.id)
        assert stored.status == TaskStatus.PENDING
        assert stored.resume_from == TaskStatus.DELETING_SOURCE

    async def test_worker_builds_device_slots_from_settings(self, worker_factory, worker_settings):
        # Given settings with tasks.max_concurrent 3 and 1 slot per local device
        payload = worker_settings.model_dump()
        payload["tasks"]["max_concurrent"] = 3
        payload["tasks"]["slots_per_device"] = {"local_fs": 1, "s3": 2}
        settings = Settings.model_validate(payload)

        # When the worker is built
        slots = worker_factory(settings=settings).service.copy_slots

        # Then its migration service limits copies to 3 in total and 1 per local device
        source = slots.devices_of(SOURCE_DB)[0]
        assert source.limit == 1
        held = [slots.hold([Device(name, 1)]) for name in ("a", "b", "c")]
        for slot in held:
            await slot.__aenter__()
        fourth = asyncio.create_task(self._enter_and_leave(slots, Device("d", 1)))
        await asyncio.sleep(0.05)
        assert not fourth.done()
        for slot in held:
            await slot.__aexit__(None, None, None)
        await asyncio.wait_for(fourth, timeout=1)

    @staticmethod
    async def _enter_and_leave(slots, device):
        async with slots.hold([device]):
            pass


class TestWebProcess:
    @pytest.fixture(autouse=True)
    def _reset_web_infrastructure(self):
        yield
        context_module._task_infrastructure = None

    async def test_web_startup_leaves_pending_tasks_to_the_worker(
        self, worker_settings, init_db, task_factory,
    ):
        # Given a PENDING migration task and one left in DB_UPDATED
        pending = await task_factory()
        orphan = await task_factory(
            source_path="Test-category/Test-resource/movie_b.mp4",
            target_path="Target-category/Target-resource/movie_b.mp4",
            status=TaskStatus.DB_UPDATED,
        )

        # When the web process's task infrastructure starts
        infrastructure = await context_module.init_task_infrastructure()
        try:
            await asyncio.sleep(0.1)

            # Then both tasks keep their stored status
            assert (await MigrationTaskModel.get(pending.id)).status == TaskStatus.PENDING
            assert (await MigrationTaskModel.get(orphan.id)).status == TaskStatus.DB_UPDATED
        finally:
            await infrastructure.shutdown()
