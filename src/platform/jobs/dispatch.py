from enum import StrEnum
from time import time

from beanie.operators import Eq, Or, Set
from bson import ObjectId
from taskiq import AsyncBroker
from taskiq.exceptions import SendTaskError
from taskiq.kicker import AsyncKicker
from taskiq_redis import RedisStreamBroker

from src.logger import get_logger
from src.platform.jobs.state_machine import TaskStateMachine
from src.platform.jobs.task_model import BaseTaskModel, TaskStatus

logger = get_logger("dispatch")

RUN_TASK = "run_task"

class Queue(StrEnum):
    """
    One queue per worker process.

    A queue is a deployment fact — which process drains it — so the names are written
    down here, once, and both the web process and the workers take them from here.
    """

    MIGRATION = "migration"


def build_broker(queue: str, redis_url: str, prefix: str) -> RedisStreamBroker:
    """
    Build the Redis Stream broker for one queue.

    The stream key and consumer group must be given explicitly: taskiq-redis defaults both
    to ``"taskiq"``, which would put every queue on one stream, drained by whichever worker
    happens to read first.

    Messages are acknowledged on receipt (``--ack-type when_received``): Mongo, not the
    stream, records whether a task ran, so a message lost after its ack is resent by
    reconciliation rather than by the broker's redelivery — which would otherwise re-send a
    migration still copying after ``idle_timeout``.

    :param queue: Queue name, e.g. ``Queue.MIGRATION``.
    :type queue: str
    :param redis_url: Redis the web process and the queue's worker share.
    :type redis_url: str
    :param prefix: Key prefix shared with the cache and the progress channels.
    :type prefix: str
    The consumer group starts at the beginning of the stream (``consumer_id="0"``), not
    taskiq's ``"$"``. The worker re-sends recovered tasks from its startup hook, which
    taskiq-redis runs *before* it creates the group; created at ``"$"`` on a first start,
    the group would skip exactly those messages. Replaying old entries instead is
    harmless — the claim drops them — and ``maxlen`` keeps there from being many.

    :return: A broker that reads and writes only this queue's stream.
    :rtype: RedisStreamBroker
    """
    return RedisStreamBroker(
        redis_url,
        queue_name=f"{prefix}:queue:{queue}",
        consumer_group_name=f"{prefix}:{queue}-worker",
        consumer_id="0",
        maxlen=10_000,
    )


class TaskDispatcher:
    """
    Puts task ids on one queue, and puts them back when they went missing.

    Bound to one queue's broker and the document type that queue carries. Used by the web
    process to start work, and by the queue's worker to recover and reconcile it.
    """

    def __init__(self, broker: AsyncBroker, task_model: type[BaseTaskModel]):
        """
        :param broker: The queue's broker.
        :type broker: AsyncBroker
        :param task_model: Document type of the tasks on this queue.
        :type task_model: type[BaseTaskModel]
        """
        self._broker = broker
        self._task_model = task_model

    async def submit(self, task_id: str) -> None:
        """
        Deliver a task id to the queue's worker.

        ``dispatched_at`` is stamped first, then the message sent. A broker failure is
        logged rather than raised: the task is already stored as PENDING, and
        reconciliation sends it once its ``dispatched_at`` goes stale. The caller — a user
        who just created a migration — gets a queued task either way.

        :param task_id: String form of the task's ObjectId.
        :type task_id: str
        :rtype: None
        """
        model = self._task_model
        await model.find_one(model.id == ObjectId(task_id)).update(
            Set({model.dispatched_at: time()})
        )
        try:
            await AsyncKicker(RUN_TASK, self._broker, labels={}).kiq(task_id)
        except SendTaskError as e:
            logger.warning(f"Could not dispatch task {task_id}, left for reconciliation: {e}")

    async def reconcile(self, stale_after: float) -> int:
        """
        Send again every PENDING task whose last dispatch is older than ``stale_after``.

        Covers a Redis restart that lost messages while the worker kept running. Only
        PENDING tasks qualify, so there is never a need to ask whether a task is still
        alive: anything past PENDING has been claimed by the worker.

        :param stale_after: Seconds after a dispatch before it is presumed lost. Zero sends
            every PENDING task.
        :type stale_after: float
        :return: How many tasks were sent.
        :rtype: int
        """
        model = self._task_model
        cutoff = time() - stale_after
        stale = await model.find(
            model.status == TaskStatus.PENDING,
            Or(Eq(model.dispatched_at, None), model.dispatched_at <= cutoff),
        ).to_list()
        for task in stale:
            await self.submit(str(task.id))
        if stale:
            logger.info(f"Reconciled {len(stale)} undelivered {self._task_model.__name__} task(s)")
        return len(stale)

    async def recover(self, executor: TaskStateMachine) -> None:
        """
        Re-queue everything this queue's previous worker left unfinished.

        Called once when the worker starts: tasks stopped mid-phase are rewound by the
        executor, and those plus every PENDING task are sent again. Duplicates of messages
        still on the stream are dropped by the claim.

        :param executor: The state machine that runs this queue's tasks.
        :type executor: TaskStateMachine
        :rtype: None
        """
        planned = await executor.plan_recovery()
        for task_id in planned:
            await self.submit(task_id)
        if planned:
            logger.info(f"Recovered {len(planned)} {self._task_model.__name__} task(s)")

    async def close(self) -> None:
        """Release the broker's connections. Only for a dispatcher from ``open_dispatcher``."""
        await self._broker.shutdown()


async def open_dispatcher(
    queue: str, redis_url: str, prefix: str, task_model: type[BaseTaskModel]
) -> TaskDispatcher:
    """
    Connect a process that only sends work — the web process — to one queue.

    Starting the broker also creates the queue's consumer group, so messages sent before
    the worker's first start are kept for it. A worker gets its broker from the taskiq
    CLI instead, which starts and stops it.

    :param queue: Queue name, e.g. ``Queue.MIGRATION``.
    :type queue: str
    :param redis_url: Redis the queue lives in.
    :type redis_url: str
    :param prefix: Key prefix shared with the cache and the progress channels.
    :type prefix: str
    :param task_model: Document type of the tasks on this queue.
    :type task_model: type[BaseTaskModel]
    :return: A dispatcher whose broker is running; ``close`` it on shutdown.
    :rtype: TaskDispatcher
    """
    broker = build_broker(queue, redis_url, prefix)
    await broker.startup()
    return TaskDispatcher(broker, task_model)
