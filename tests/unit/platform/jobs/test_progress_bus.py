"""Progress frames travelling from a worker process to the web process over Redis.

Runs against the real Redis testcontainer: publishing, the ``latest`` key, the single
pattern subscription in the web process and the watchdog are all exercised for real.
"""

import asyncio
import json
import uuid

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from src.platform.jobs.progress import ProgressFrame
from src.platform.jobs.progress_bus import ProgressBus, ProgressPublisher
from src.platform.jobs.task_model import TaskStatus

pytestmark = pytest.mark.unit


def _frame(task_id: str, status: TaskStatus, current: int = 0, total: int = 100) -> ProgressFrame:
    return ProgressFrame(task_id=task_id, status=status.value, current=current, total=total)


class _Snapshots:
    """A stand-in for the DB snapshot lookup: returns whatever state the test sets."""

    def __init__(self, frame: ProgressFrame | None = None):
        self.frame = frame
        self.calls: list[str] = []

    async def __call__(self, task_id: str) -> ProgressFrame | None:
        self.calls.append(task_id)
        return self.frame


@pytest_asyncio.fixture
async def redis(redis_url):
    client = Redis.from_url(redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def prefix() -> str:
    # A fresh namespace per test, so frames from one test can never reach another.
    return f"pfx-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def publisher(redis, prefix) -> ProgressPublisher:
    return ProgressPublisher(redis, prefix)


@pytest_asyncio.fixture
async def bus_factory(redis, prefix):
    buses: list[ProgressBus] = []

    async def _create(**kwargs) -> ProgressBus:
        bus = ProgressBus(redis, prefix, **kwargs)
        await bus.start()
        buses.append(bus)
        return bus

    yield _create
    for bus in buses:
        await bus.stop()


async def _rest(stream, timeout: float = 2.0) -> list[ProgressFrame]:
    """Consume a stream to its end, failing the test if it does not end in time."""

    async def _collect():
        return [frame async for frame in stream]

    return await asyncio.wait_for(_collect(), timeout)


class TestPublisher:
    async def test_published_frame_is_stored_as_latest_with_a_short_ttl(self, redis):
        # Given a ProgressPublisher on prefix "pfx"
        prefix = f"pfx-{uuid.uuid4().hex[:8]}"
        publisher = ProgressPublisher(redis, prefix)

        # When it publishes a PROCESSING frame for task "t1" at 40 of 100
        await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 40))

        # Then key "pfx:task:t1:latest" holds that frame
        stored = json.loads(await redis.get(f"{prefix}:task:t1:latest"))
        assert stored["status"] == "PROCESSING"
        assert stored["current"] == 40
        assert stored["total"] == 100
        # And the key's remaining TTL is between 1 and 60 seconds
        assert 0 < await redis.ttl(f"{prefix}:task:t1:latest") <= 60


class TestObserve:
    async def test_observer_opens_with_the_latest_frame(self, bus_factory, publisher):
        # Given task "t1" whose latest frame is PROCESSING at 40 of 100
        bus = await bus_factory()
        await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 40))
        snapshots = _Snapshots(_frame("t1", TaskStatus.PENDING))

        # When a client observes "t1"
        stream = bus.observe("t1", snapshots)
        first = await anext(stream)
        await stream.aclose()

        # Then the first frame it receives is that PROCESSING frame at 40
        assert (first.status, first.current) == ("PROCESSING", 40)
        # And the DB snapshot function is not called
        assert snapshots.calls == []

    async def test_observer_opens_with_the_db_snapshot_when_no_latest_frame_exists(
        self, bus_factory
    ):
        # Given task "t1" with no latest frame in Redis
        bus = await bus_factory()
        # And a snapshot function that returns a PENDING frame for "t1"
        snapshots = _Snapshots(_frame("t1", TaskStatus.PENDING))

        # When a client observes "t1"
        stream = bus.observe("t1", snapshots)
        first = await anext(stream)
        await stream.aclose()

        # Then the first frame it receives is that PENDING frame
        assert first.status == "PENDING"
        assert snapshots.calls == ["t1"]

    async def test_observer_follows_live_frames_until_a_terminal_frame(
        self, bus_factory, publisher
    ):
        # Given a client observing PENDING task "t1"
        bus = await bus_factory()
        stream = bus.observe("t1", _Snapshots(_frame("t1", TaskStatus.PENDING)))
        opening = await anext(stream)

        # When a publisher sends PROCESSING 10, PROCESSING 50, then COMPLETED 100 for "t1"
        await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 10))
        await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 50))
        await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100))

        # Then the client receives the opening frame followed by those three frames in order
        # And the stream ends after the COMPLETED frame
        rest = await _rest(stream)
        assert opening.status == "PENDING"
        assert [(f.status, f.current) for f in rest] == [
            ("PROCESSING", 10), ("PROCESSING", 50), ("COMPLETED", 100),
        ]

    async def test_observing_a_settled_task_yields_its_state_and_ends(self, bus_factory):
        # Given task "t1" whose snapshot is COMPLETED and no latest frame exists
        bus = await bus_factory()
        snapshots = _Snapshots(_frame("t1", TaskStatus.COMPLETED, 100))

        # When a client observes "t1"
        frames = await _rest(bus.observe("t1", snapshots))

        # Then it receives exactly the COMPLETED frame and the stream ends
        assert [f.status for f in frames] == ["COMPLETED"]

    async def test_every_observer_of_a_task_receives_every_frame(self, bus_factory, publisher):
        # Given two clients observing PENDING task "t1"
        bus = await bus_factory()
        snapshots = _Snapshots(_frame("t1", TaskStatus.PENDING))
        first, second = bus.observe("t1", snapshots), bus.observe("t1", snapshots)
        await anext(first)
        await anext(second)

        # When a publisher sends PROCESSING 30 then COMPLETED 100 for "t1"
        await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 30))
        await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100))

        # Then each client receives both frames
        for stream in (first, second):
            assert [f.status for f in await _rest(stream)] == ["PROCESSING", "COMPLETED"]

    async def test_frames_of_another_task_are_not_delivered(self, bus_factory, publisher):
        # Given a client observing PENDING task "t1"
        bus = await bus_factory()
        stream = bus.observe("t1", _Snapshots(_frame("t1", TaskStatus.PENDING)))
        await anext(stream)

        # When a publisher sends PROCESSING 30 for "t2" and then COMPLETED for "t1"
        await publisher.publish(_frame("t2", TaskStatus.PROCESSING, 30))
        await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100))

        # Then the client never receives a frame for "t2"
        assert [f.task_id for f in await _rest(stream)] == ["t1"]

    async def test_detaching_one_observer_leaves_the_others_receiving(
        self, bus_factory, publisher
    ):
        # Given two clients observing PENDING task "t1"
        bus = await bus_factory()
        snapshots = _Snapshots(_frame("t1", TaskStatus.PENDING))
        first, second = bus.observe("t1", snapshots), bus.observe("t1", snapshots)
        await anext(first)
        await anext(second)

        # When the first client stops consuming its stream
        await first.aclose()
        # And a publisher sends COMPLETED for "t1"
        await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100))

        # Then the second client still receives the COMPLETED frame
        assert [f.status for f in await _rest(second)] == ["COMPLETED"]


class TestWatchdog:
    async def test_stream_ends_when_the_task_settled_without_a_terminal_frame(
        self, bus_factory
    ):
        # Given a bus with a 0.2 second watchdog
        bus = await bus_factory(watchdog_interval=0.2)
        # And a client observing task "t1" whose snapshot is PENDING
        snapshots = _Snapshots(_frame("t1", TaskStatus.PENDING))
        stream = bus.observe("t1", snapshots)
        await anext(stream)

        # When the snapshot turns CANCELLED and no frame is ever published
        snapshots.frame = _frame("t1", TaskStatus.CANCELLED)

        # Then the client receives the CANCELLED snapshot and the stream ends
        assert [f.status for f in await _rest(stream)] == ["CANCELLED"]

    async def test_stream_keeps_waiting_while_the_task_is_still_active(
        self, bus_factory, publisher
    ):
        # Given a bus with a 0.2 second watchdog
        bus = await bus_factory(watchdog_interval=0.2)
        # And a client observing task "t1" whose snapshot stays PROCESSING
        stream = bus.observe("t1", _Snapshots(_frame("t1", TaskStatus.PROCESSING, 5)))
        await anext(stream)
        rest = asyncio.create_task(_rest(stream, timeout=5))

        # When one second passes without any frame
        await asyncio.sleep(1)
        assert not rest.done()
        # And then a publisher sends COMPLETED for "t1"
        await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100))

        # Then the client's stream ends with that COMPLETED frame
        frames = await rest
        assert frames[-1].status == "COMPLETED"


class TestSlowObserver:
    async def test_a_lagging_observer_loses_its_oldest_frames_not_the_newest(
        self, bus_factory, publisher
    ):
        # Given a bus whose observer channels hold 2 frames
        bus = await bus_factory(channel_size=2)
        # And a client observing task "t1" that does not consume
        stream = bus.observe("t1", _Snapshots(_frame("t1", TaskStatus.PENDING)))
        await anext(stream)

        # When 5 PROCESSING frames at 1..5 are published followed by COMPLETED
        for current in range(1, 6):
            await publisher.publish(_frame("t1", TaskStatus.PROCESSING, current))
        await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100))
        await asyncio.sleep(0.3)

        # Then once the client resumes consuming, the last frame it receives is COMPLETED
        frames = await _rest(stream)
        assert frames[-1].status == "COMPLETED"
        # And it receives fewer than 6 live frames
        assert len(frames) < 6


class TestStaleLatestFrame:
    """The latest frame outlives its run by up to a minute, so it can describe a run that
    has since been superseded — a failed run that was retried straight away."""

    # Scenario: a retried task is not reported as still failed
    #   Given task "t1" whose latest frame is FAILED from an earlier run
    #   And a snapshot function that returns a PENDING frame for "t1", as after a retry
    #   When a client observes "t1"
    #   Then the first frame it receives is the PENDING snapshot, not the FAILED frame
    #   And when the publisher then sends PROCESSING 50 and COMPLETED 100
    #   Then the client receives those frames and the stream ends after COMPLETED
    async def test_terminal_latest_frame_contradicted_by_the_store_is_not_reported(
        self, bus_factory, publisher
    ):
        bus = await bus_factory()
        await publisher.publish(_frame("t1", TaskStatus.FAILED, 30))
        snapshots = _Snapshots(_frame("t1", TaskStatus.PENDING))

        stream = bus.observe("t1", snapshots)
        first = await asyncio.wait_for(anext(stream), timeout=2)

        assert first.status == "PENDING"
        await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 50))
        await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100))
        rest = await _rest(stream)
        assert [(f.status, f.current) for f in rest] == [("PROCESSING", 50), ("COMPLETED", 100)]

    # Scenario: a terminal latest frame that the store agrees with still ends the stream
    #   Given task "t1" whose latest frame is COMPLETED at 100
    #   And a snapshot function that returns a COMPLETED frame for "t1"
    #   When a client observes "t1"
    #   Then it receives exactly the COMPLETED frame at 100 and the stream ends
    async def test_terminal_latest_frame_confirmed_by_the_store_ends_the_stream(
        self, bus_factory, publisher
    ):
        bus = await bus_factory()
        await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100))
        snapshots = _Snapshots(_frame("t1", TaskStatus.COMPLETED, 100))

        frames = await _rest(bus.observe("t1", snapshots))

        assert [(f.status, f.current) for f in frames] == [("COMPLETED", 100)]
