"""Delivering task ids to the worker of a queue, and re-delivering what got lost.

Mongo is the source of truth: a message only ever carries a task id, so duplicates are
harmless (the claim drops them) and reconciliation is free to send again.
"""

import time

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from taskiq import InMemoryBroker

from src.platform.jobs.dispatch import RUN_TASK, Queue, TaskDispatcher, build_broker
from src.platform.jobs.task_model import TaskStatus
from tests.unit.platform.jobs.reindex import ReindexStateMachine, ReindexTaskModel

pytestmark = pytest.mark.unit


class _RecordingBroker(InMemoryBroker):
    """A real taskiq broker whose worker side just writes down the ids it receives."""

    def __init__(self):
        super().__init__(await_inplace=True)
        self.delivered: list[str] = []

        async def run_task(task_id: str) -> None:
            self.delivered.append(task_id)

        self.register_task(run_task, task_name=RUN_TASK)


class _UnreachableBroker(InMemoryBroker):
    async def kick(self, message) -> None:
        raise RedisConnectionError("Redis is down")


@pytest.fixture
def broker() -> _RecordingBroker:
    return _RecordingBroker()


@pytest.fixture
def dispatcher(broker) -> TaskDispatcher:
    return TaskDispatcher(broker, ReindexTaskModel)


class TestQueueBrokers:
    def test_each_queue_reads_its_own_stream_and_consumer_group(self):
        # Given key prefix "video-app"
        # When brokers are built for the "migration" and "scan" queues
        migration = build_broker(Queue.MIGRATION, "redis://localhost:6379/0", "video-app")
        scan = build_broker("scan", "redis://localhost:6379/0", "video-app")

        # Then their stream keys differ from each other and from taskiq's default "taskiq"
        assert len({migration.queue_name, scan.queue_name, "taskiq"}) == 3
        # And their consumer group names differ from each other
        assert migration.consumer_group_name != scan.consumer_group_name
        # And both stream keys start with "video-app:"
        assert migration.queue_name.startswith("video-app:")
        assert scan.queue_name.startswith("video-app:")


class TestSubmit:
    async def test_submit_stamps_dispatched_at_and_delivers_the_task_id(
        self, reindex_task_factory, broker, dispatcher
    ):
        # Given a PENDING reindex task with no dispatched_at
        task = await reindex_task_factory()
        # And a dispatcher on an in-memory broker that records delivered ids

        # When the task is submitted
        before = time.time()
        await dispatcher.submit(str(task.id))

        # Then the broker delivered exactly that task id
        assert broker.delivered == [str(task.id)]
        # And the stored dispatched_at is set to about now
        stored = await ReindexTaskModel.get(task.id)
        assert before <= stored.dispatched_at <= time.time()

    async def test_submit_does_not_raise_when_the_broker_is_unreachable(
        self, reindex_task_factory
    ):
        # Given a PENDING reindex task
        task = await reindex_task_factory()
        # And a dispatcher whose broker raises on every kick
        dispatcher = TaskDispatcher(_UnreachableBroker(), ReindexTaskModel)

        # When the task is submitted
        # Then no exception reaches the caller
        await dispatcher.submit(str(task.id))

        # And the task is still PENDING, left for reconciliation
        assert (await ReindexTaskModel.get(task.id)).status == TaskStatus.PENDING


class TestReconcile:
    async def test_pending_tasks_dispatched_too_long_ago_are_delivered_again(
        self, reindex_task_factory, broker, dispatcher
    ):
        # Given two PENDING reindex tasks, one dispatched 10 minutes ago and one never dispatched
        stale = await reindex_task_factory(dispatched_at=time.time() - 600)
        never = await reindex_task_factory()

        # When reconcile runs with a 5 minute staleness window
        await dispatcher.reconcile(stale_after=300)

        # Then both task ids are delivered
        assert sorted(broker.delivered) == sorted([str(stale.id), str(never.id)])

    async def test_recently_dispatched_pending_task_is_left_alone(
        self, reindex_task_factory, broker, dispatcher
    ):
        # Given a PENDING reindex task dispatched 1 minute ago
        await reindex_task_factory(dispatched_at=time.time() - 60)

        # When reconcile runs with a 5 minute staleness window
        await dispatcher.reconcile(stale_after=300)

        # Then nothing is delivered
        assert broker.delivered == []

    async def test_tasks_past_pending_are_never_delivered_again(
        self, reindex_task_factory, broker, dispatcher
    ):
        # Given reindex tasks in PROCESSING, COMPLETED and FAILED, all dispatched 10 minutes ago
        for status in (TaskStatus.PROCESSING, TaskStatus.COMPLETED, TaskStatus.FAILED):
            await reindex_task_factory(status=status, dispatched_at=time.time() - 600)

        # When reconcile runs with a 5 minute staleness window
        await dispatcher.reconcile(stale_after=300)

        # Then nothing is delivered
        assert broker.delivered == []


class TestRecover:
    async def test_recover_delivers_orphans_and_every_pending_task(
        self, reindex_task_factory, broker, dispatcher
    ):
        # Given a reindex task left in DB_UPDATED and a PENDING one dispatched 1 minute ago
        orphan = await reindex_task_factory(status=TaskStatus.DB_UPDATED)
        pending = await reindex_task_factory(dispatched_at=time.time() - 60)
        # And a COMPLETED reindex task
        await reindex_task_factory(status=TaskStatus.COMPLETED)

        # When the dispatcher recovers its queue with the reindex machine
        await dispatcher.recover(ReindexStateMachine())

        # Then the DB_UPDATED and PENDING task ids are delivered, and the COMPLETED one is not
        assert sorted(broker.delivered) == sorted([str(orphan.id), str(pending.id)])
        # And the orphan is stored as PENDING with resume_from DELETING_SOURCE
        stored = await ReindexTaskModel.get(orphan.id)
        assert stored.status == TaskStatus.PENDING
        assert stored.resume_from == TaskStatus.DELETING_SOURCE
