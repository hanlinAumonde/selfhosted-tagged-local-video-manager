"""The migration worker running batch children: the window, the hand-off to the next
child, the batch progress channel and the one directory refresh at the end.

The web process sends every child of a batch at once; the worker only lets two of them
run at a time and leaves the rest PENDING. A dropped delivery costs one document read, so
it never holds up a migration queued behind the batch.
"""

import asyncio
import json

import pytest

from src.config import Settings
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus
from tests.unit.features.migration.batch_helpers import (
    SOURCE_ROOT,
    TARGET_ROOT,
    add_child,
    make_batch,
    record_directory_refreshes,
)
from tests.unit.test_worker import _RecordingBroker, redis, worker_factory  # noqa: F401  (fixtures)

pytestmark = pytest.mark.unit


@pytest.fixture
def worker_settings(two_category_settings: Settings, redis_url: str, monkeypatch) -> Settings:
    # Enough copy slots per disk that two children of a batch really copy side by side;
    # otherwise the second one waits for the disk and the window is never what holds it back.
    payload = two_category_settings.model_dump()
    payload["tasks"]["redis_url"] = redis_url
    payload["cache_config"]["key_prefix"] = "worker-test"
    payload["tasks"]["slots_per_device"] = {"local_fs": 4, "s3": 4}
    settings = Settings.model_validate(payload)
    monkeypatch.setattr("src.config._settings", settings)
    return settings


async def _videos_for(video_factory, *relative_paths: str) -> None:
    for relative in relative_paths:
        name = relative.rsplit("/", 1)[-1].removesuffix(".mp4")
        await video_factory(name=name, path=f"{SOURCE_ROOT}/{relative}")


def _block_copies(worker, blocked_names: set[str]) -> asyncio.Event:
    """Hold the copy of each named file until the returned event is set."""
    release = asyncio.Event()
    target_handler = worker.service.resourceHandlerService.get_handler("Target-category")
    write = target_handler.write_file_streaming

    async def write_when_released(path, chunks):
        if any(name in path for name in blocked_names):
            await release.wait()
        await write(path, chunks)

    target_handler.write_file_streaming = write_when_released
    return release


async def _until_status(task, status: TaskStatus, timeout: float = 3.0) -> None:
    async def _poll():
        while (await MigrationTaskModel.get(task.id)).status != status:
            await asyncio.sleep(0.02)

    await asyncio.wait_for(_poll(), timeout)


class TestBatchWindowInTheWorker:
    async def test_a_third_child_is_left_pending_while_two_children_are_held(
        self, worker_factory, video_factory, task_factory,
    ):
        """
        Scenario: the worker holds at most two children of a batch
          Given a batch with PENDING children "movie_a.mp4", "movie_b.mp4" and
            "subdir/movie_c.mp4"
          And the copies of "movie_a.mp4" and "movie_b.mp4" are blocked mid-way
          When the worker receives all three children
          Then "movie_a.mp4" and "movie_b.mp4" are PROCESSING
          And "movie_c.mp4" is still PENDING
          And the run for "movie_c.mp4" has returned
        """
        await _videos_for(video_factory, "movie_a.mp4", "movie_b.mp4", "subdir/movie_c.mp4")
        batch = await make_batch()
        a = await add_child(task_factory, batch, "movie_a")
        b = await add_child(task_factory, batch, "movie_b")
        c = await add_child(task_factory, batch, "movie_c", sub_dir="subdir/")
        worker = worker_factory()
        release = _block_copies(worker, {"movie_a", "movie_b"})

        runs = [asyncio.create_task(worker.run(str(t.id))) for t in (a, b)]
        try:
            await _until_status(a, TaskStatus.PROCESSING)
            await _until_status(b, TaskStatus.PROCESSING)

            await asyncio.wait_for(worker.run(str(c.id)), timeout=2)

            assert (await MigrationTaskModel.get(c.id)).status == TaskStatus.PENDING
        finally:
            release.set()
            await asyncio.gather(*runs)

    async def test_a_task_outside_any_batch_is_not_held_back_by_a_busy_batch(
        self, worker_factory, video_factory, task_factory,
    ):
        """
        Scenario: a single migration queued behind a busy batch still runs
          Given a batch whose two children are held by the worker with blocked copies
          And a PENDING migration task for "movie_b.mp4" outside any batch
          When the worker receives that task
          Then it runs to COMPLETED
        """
        await _videos_for(video_factory, "movie_a.mp4", "movie_b.mp4", "subdir/movie_c.mp4")
        batch = await make_batch()
        a = await add_child(task_factory, batch, "movie_a")
        c = await add_child(task_factory, batch, "movie_c", sub_dir="subdir/")
        single = await task_factory(
            source_path=f"{SOURCE_ROOT}/movie_b.mp4", target_path=f"{TARGET_ROOT}/movie_b.mp4"
        )
        worker = worker_factory()
        release = _block_copies(worker, {"movie_a", "movie_c"})

        runs = [asyncio.create_task(worker.run(str(t.id))) for t in (a, c)]
        try:
            await _until_status(a, TaskStatus.PROCESSING)
            await _until_status(c, TaskStatus.PROCESSING)

            await asyncio.wait_for(worker.run(str(single.id)), timeout=5)

            assert (await MigrationTaskModel.get(single.id)).status == TaskStatus.COMPLETED
        finally:
            release.set()
            await asyncio.gather(*runs)


class TestHandOffToTheNextChild:
    async def test_a_finished_child_dispatches_the_next_pending_sibling(
        self, worker_factory, video_factory, task_factory,
    ):
        """
        Scenario: a child that ends makes room for the next one
          Given a batch with PENDING children "movie_a.mp4", "movie_b.mp4" and
            "subdir/movie_c.mp4", created in that order
          And the worker holds "movie_b.mp4" with a blocked copy
          And a broker that records deliveries
          When the worker runs "movie_a.mp4" to COMPLETED
          Then the id of "movie_c.mp4" is delivered to the migration queue
          And the id of "movie_b.mp4" is not delivered again
        """
        await _videos_for(video_factory, "movie_a.mp4", "movie_b.mp4", "subdir/movie_c.mp4")
        batch = await make_batch()
        a = await add_child(task_factory, batch, "movie_a")
        b = await add_child(task_factory, batch, "movie_b")
        c = await add_child(task_factory, batch, "movie_c", sub_dir="subdir/")
        broker = _RecordingBroker()
        worker = worker_factory(broker=broker)
        release = _block_copies(worker, {"movie_b"})

        held = asyncio.create_task(worker.run(str(b.id)))
        try:
            await _until_status(b, TaskStatus.PROCESSING)

            await worker.run(str(a.id))

            assert (await MigrationTaskModel.get(a.id)).status == TaskStatus.COMPLETED
            assert broker.delivered == [str(c.id)]
        finally:
            release.set()
            await held

    async def test_a_child_cancelled_while_queued_still_hands_off(
        self, worker_factory, task_factory,
    ):
        """
        Scenario: a delivery for a child cancelled while queued frees no place but still
          moves the batch on
          Given a batch with children "movie_a.mp4" CANCELLED and "movie_b.mp4" PENDING
          And a broker that records deliveries
          When the worker receives "movie_a.mp4"
          Then the id of "movie_b.mp4" is delivered to the migration queue
        """
        batch = await make_batch()
        cancelled = await add_child(task_factory, batch, "movie_a", TaskStatus.CANCELLED)
        pending = await add_child(task_factory, batch, "movie_b")
        broker = _RecordingBroker()
        worker = worker_factory(broker=broker)

        await worker.run(str(cancelled.id))

        assert broker.delivered == [str(pending.id)]


class TestBatchProgressChannel:
    async def test_child_frames_are_also_published_on_the_batch_channel(
        self, worker_factory, redis, video_factory, task_factory,
    ):
        """
        Scenario: observers of the batch see each child's frames
          Given a batch with one PENDING child "movie_a.mp4"
          And a subscriber to that batch's progress channel
          When the worker runs that child to COMPLETED
          Then the subscriber receives frames for that child's task id
          And the last of them is COMPLETED
        """
        await _videos_for(video_factory, "movie_a.mp4")
        batch = await make_batch()
        child = await add_child(task_factory, batch, "movie_a")
        worker = worker_factory()
        pubsub = redis.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(f"worker-test:batch:{batch.id}:progress")
        try:
            await worker.run(str(child.id))

            # A filtered subscribe confirmation reads as None too, so read for a fixed window.
            frames = []
            deadline = asyncio.get_running_loop().time() + 0.5
            while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
                message = await pubsub.get_message(timeout=remaining)
                if message is not None:
                    frames.append(json.loads(message["data"]))
        finally:
            await pubsub.aclose()

        assert frames
        assert {f["task_id"] for f in frames} == {str(child.id)}
        assert frames[-1]["status"] == "COMPLETED"


class TestDirectoryRefreshAtTheEnd:
    async def test_the_last_child_to_end_refreshes_the_batch_directories(
        self, worker_factory, video_factory, task_factory,
    ):
        """
        Scenario: the batch's directories are refreshed once, after its last child
          Given a batch with PENDING children "movie_a.mp4" and "subdir/movie_c.mp4"
          When the worker runs "movie_a.mp4" to COMPLETED
          Then no directory metadata has been refreshed
          When the worker runs "movie_c.mp4" to COMPLETED
          Then the Test-resource root, "subdir" and the target directory are each
            refreshed exactly once
        """
        await _videos_for(video_factory, "movie_a.mp4", "subdir/movie_c.mp4")
        batch = await make_batch()
        a = await add_child(task_factory, batch, "movie_a")
        c = await add_child(task_factory, batch, "movie_c", sub_dir="subdir/")
        worker = worker_factory()
        refreshed = record_directory_refreshes(worker.service)

        await worker.run(str(a.id))
        assert refreshed == []

        await worker.run(str(c.id))
        assert sorted(refreshed) == sorted([
            ("Test-category", SOURCE_ROOT),
            ("Test-category", f"{SOURCE_ROOT}/subdir"),
            ("Target-category", TARGET_ROOT),
        ])
