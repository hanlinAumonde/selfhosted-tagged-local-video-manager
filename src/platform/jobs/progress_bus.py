import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
import json
from typing import Any

from src.constants.redis import BATCH_NAMESPACE, LATEST_FRAME, PROGRESS_CHANNEL, TASK_NAMESPACE
from src.logger import get_logger
from src.platform.jobs.progress import ProgressFrame
from src.platform.jobs.state_machine import TaskStateMachine
from src.platform.redis.redis_service import REDIS_UNAVAILABLE, RedisService

logger = get_logger("progress_bus")

#: Looks up a task's stored state, for observers that have no live frame to start from.
SnapshotFn = Callable[[str], Awaitable[ProgressFrame | None]]

#: Counts a batch's tasks from the store; None when there is no such batch.
SummarizeFn = Callable[[str], Awaitable[Any]]

_END_OF_STREAM = object()


def _progress_channel(redis: RedisService, task_id: str) -> str:
    return redis.key(TASK_NAMESPACE, task_id, PROGRESS_CHANNEL)


def _batch_channel(redis: RedisService, batch_id: str) -> str:
    return redis.key(BATCH_NAMESPACE, batch_id, PROGRESS_CHANNEL)


def _batch_id_of(redis: RedisService, channel: str) -> str:
    """The batch id inside a channel name built by ``_batch_channel``."""
    head = redis.key(BATCH_NAMESPACE, "")
    return channel[len(head):-len(f":{PROGRESS_CHANNEL}")]


def _latest_key(redis: RedisService, task_id: str) -> str:
    return redis.key(TASK_NAMESPACE, task_id, LATEST_FRAME)


def _encode(frame: ProgressFrame) -> str:
    return json.dumps(asdict(frame))


def _decode(raw: str | bytes) -> ProgressFrame:
    return ProgressFrame(**json.loads(raw))


def _is_terminal(frame: ProgressFrame) -> bool:
    return frame.status in TaskStateMachine.TERMINAL_STATUSES


@dataclass(frozen=True)
class BatchEvent:
    """
    What an observer of a batch receives.

    ``summary`` comes with the opening event, with every task that ends, and from the
    watchdog — the moments the counts can have changed. ``frame`` is a task's own frame,
    relayed as is.
    """

    summary: Any = None
    frame: ProgressFrame | None = None


class ProgressPublisher:
    """
    The worker's side of the bus: sends each frame a task produces to whoever is watching.

    Every frame is published on the task's channel and also stored as the task's latest
    frame, so an observer that attaches between two frames still opens with fresh numbers
    rather than with the database's throttled copy.
    """

    def __init__(self, redis: RedisService, latest_frame_ttl: int):
        """
        :param redis: The Redis the web process subscribes to.
        :type redis: RedisService
        :param latest_frame_ttl: Seconds the latest frame outlives its task's last report.
            Long enough for a client that reconnects mid-task; short enough that nothing
            has to clean it up.
        :type latest_frame_ttl: int
        """
        self._redis = redis
        self._latest_frame_ttl = latest_frame_ttl

    async def publish(self, frame: ProgressFrame, batch_id: str | None = None) -> None:
        """
        Send one frame to the task's observers, and to its batch's when it has one.

        A Redis failure is logged and swallowed. Progress is advisory: a migration must
        not fail because nobody could be told how far it got, and observers fall back to
        the database once frames stop arriving.

        :param frame: The frame to deliver.
        :type frame: ProgressFrame
        :param batch_id: The batch the task belongs to, if any.
        :type batch_id: str | None
        :rtype: None
        """
        payload = _encode(frame)
        try:
            async with self._redis.client.pipeline(transaction=False) as pipe:
                pipe.publish(_progress_channel(self._redis, frame.task_id), payload)
                if batch_id is not None:
                    pipe.publish(_batch_channel(self._redis, batch_id), payload)
                pipe.set(_latest_key(self._redis, frame.task_id), payload, ex=self._latest_frame_ttl)
                await pipe.execute()
        except REDIS_UNAVAILABLE as e:
            logger.warning(f"Could not publish progress for task {frame.task_id}: {e}")

    async def relay(
        self, frames: AsyncIterable[ProgressFrame], batch_id: str | None = None
    ) -> None:
        """
        Publish every frame of a run, as it is produced.

        :param frames: The frames a state machine yields for one run.
        :type frames: AsyncIterable[ProgressFrame]
        :param batch_id: The batch the task belongs to, if any.
        :type batch_id: str | None
        :rtype: None
        """
        async for frame in frames:
            await self.publish(frame, batch_id)


class ProgressBus:
    """
    The web process's side of the bus: one Redis subscription, fanned out to every client
    watching a task.

    Two pattern subscriptions, one for tasks and one for batches, cover everything, so
    attaching an observer never costs a Redis round trip of its own and there is no
    subscribe/unsubscribe race to get wrong.
    Frames for tasks nobody watches are simply dropped.

    Each observer gets its own bounded channel. A full channel drops its oldest frame:
    clients only care about the newest numbers, and a slow browser must never hold up the
    reader every other observer depends on.
    """

    def __init__(
        self,
        redis: RedisService,
        watchdog_interval: float = 10.0,
        channel_size: int = 64,
    ):
        """
        :param redis: The Redis the workers publish to.
        :type redis: RedisService
        :param watchdog_interval: Seconds without a frame after which an observer checks
            the database. A worker that crashes, or a task cancelled before it ever ran,
            sends no final frame; without this the observer would wait forever.
        :type watchdog_interval: float
        :param channel_size: Frames buffered per observer before the oldest is dropped.
        :type channel_size: int
        """
        self._redis = redis
        self._watchdog_interval = watchdog_interval
        self._channel_size = channel_size

        self._channels: dict[str, set[asyncio.Queue]] = {}
        self._batch_channels: dict[str, set[asyncio.Queue]] = {}
        self._pubsub = None
        self._reader: asyncio.Task | None = None

    async def start(self) -> None:
        """
        Subscribe and start delivering frames. Returns once the subscription is in place,
        so a frame published afterwards is guaranteed to arrive.

        :rtype: None
        """
        self._pubsub = self._redis.client.pubsub(ignore_subscribe_messages=True)
        await self._pubsub.psubscribe(
            _progress_channel(self._redis, "*"),
            _batch_channel(self._redis, "*"),
        )
        self._reader = asyncio.create_task(self._read_loop(), name="progress-bus-reader")

    async def stop(self) -> None:
        """
        Stop reading and end every observer's stream.

        :rtype: None
        """
        if self._reader is not None:
            self._reader.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None
        if self._pubsub is not None:
            await self._pubsub.aclose()
            self._pubsub = None
        for registry in (self._channels, self._batch_channels):
            for channels in registry.values():
                for channel in channels:
                    self._offer(channel, _END_OF_STREAM)

    async def observe(
        self, task_id: str, snapshot: SnapshotFn
    ) -> AsyncGenerator[ProgressFrame, None]:
        """
        Yield progress frames for a task until it settles.

        A pure read: attaching never affects the task. The stream opens with the task's
        current state — its latest published frame, or the database snapshot when there
        is none — then follows live frames until a terminal one.

        A terminal latest frame is checked against the database before it is trusted: it
        may belong to a failed run that has just been retried.

        The channel is registered *before* the opening state is read, so a frame published
        in between is queued rather than lost. Seeing it twice is harmless.

        :param task_id: String form of the task's ObjectId.
        :type task_id: str
        :param snapshot: Reads the task's stored state; used to open the stream and by the
            watchdog.
        :type snapshot: SnapshotFn
        :yield: Progress frames, starting with the current state.
        :rtype: AsyncGenerator[ProgressFrame, None]
        """
        channel: asyncio.Queue = asyncio.Queue(maxsize=self._channel_size)
        self._channels.setdefault(task_id, set()).add(channel)
        try:
            opening = await self._read_latest(task_id)
            if opening is None or _is_terminal(opening):
                # A terminal latest frame outlives its run by up to a minute, so it may
                # describe a run a retry has since replaced; only the store can tell.
                stored = await snapshot(task_id)
                if opening is None or stored is None or not _is_terminal(stored):
                    opening = stored
            if opening is None:
                return
            yield opening
            if _is_terminal(opening):
                return

            while True:
                try:
                    frame = await asyncio.wait_for(channel.get(), self._watchdog_interval)
                except TimeoutError:
                    stored = await snapshot(task_id)
                    if stored is None:
                        return
                    if _is_terminal(stored):
                        yield stored
                        return
                    continue

                if frame is _END_OF_STREAM:
                    return
                yield frame
                if _is_terminal(frame):
                    return
        finally:
            self._detach(self._channels, task_id, channel)

    async def observe_batch(
        self,
        batch_id: str,
        summarize: SummarizeFn,
        is_settled: Callable[[Any], bool],
    ) -> AsyncGenerator[BatchEvent, None]:
        """
        Yield a batch's state, then its tasks' frames, until no task of it is active.

        A pure read, like ``observe``. The summary is opaque here: the bus only fetches it
        and asks whether it is settled. It is fetched again whenever a task ends, since
        only then can the counts change, and by the watchdog, since a task cancelled while
        queued or abandoned by a dead worker ends without a frame.

        :param batch_id: String form of the batch's ObjectId.
        :type batch_id: str
        :param summarize: Reads the batch's counts from the store.
        :type summarize: SummarizeFn
        :param is_settled: Whether a summary describes a batch with nothing left to run.
        :type is_settled: Callable[[Any], bool]
        :yield: The opening summary, then one event per relayed frame.
        :rtype: AsyncGenerator[BatchEvent, None]
        """
        channel: asyncio.Queue = asyncio.Queue(maxsize=self._channel_size)
        self._batch_channels.setdefault(batch_id, set()).add(channel)
        try:
            summary = await summarize(batch_id)
            if summary is None:
                return
            yield BatchEvent(summary=summary)
            if is_settled(summary):
                return

            while True:
                try:
                    frame = await asyncio.wait_for(channel.get(), self._watchdog_interval)
                except TimeoutError:
                    summary = await summarize(batch_id)
                    if summary is None:
                        return
                    if is_settled(summary):
                        yield BatchEvent(summary=summary)
                        return
                    continue

                if frame is _END_OF_STREAM:
                    return
                if not _is_terminal(frame):
                    yield BatchEvent(frame=frame)
                    continue
                summary = await summarize(batch_id)
                yield BatchEvent(summary=summary, frame=frame)
                if summary is None or is_settled(summary):
                    return
        finally:
            self._detach(self._batch_channels, batch_id, channel)

    @staticmethod
    def _detach(registry: dict[str, set[asyncio.Queue]], key: str, channel: asyncio.Queue) -> None:
        channels = registry.get(key)
        if channels is not None:
            channels.discard(channel)
            if not channels:
                registry.pop(key, None)

    async def _read_latest(self, task_id: str) -> ProgressFrame | None:
        try:
            raw = await self._redis.client.get(_latest_key(self._redis, task_id))
        except REDIS_UNAVAILABLE as e:
            logger.warning(f"Could not read latest progress for task {task_id}: {e}")
            return None
        return _decode(raw) if raw is not None else None

    async def _read_loop(self) -> None:
        """
        Move frames from the subscription into observer channels, for as long as the bus
        runs.

        A Redis failure is logged and retried rather than ending the loop. redis-py
        re-subscribes on reconnect, and observers ride out the gap on their watchdogs.

        :rtype: None
        """
        while True:
            try:
                message = await self._pubsub.get_message(timeout=1.0)
            except asyncio.CancelledError:
                raise
            except REDIS_UNAVAILABLE as e:
                logger.warning(f"Progress subscription interrupted, retrying: {e}")
                await asyncio.sleep(1.0)
                continue
            if message is None:
                continue
            try:
                frame = _decode(message["data"])
            except (TypeError, ValueError) as e:
                logger.warning(f"Ignoring malformed progress message: {e}")
                continue
            # A batch task's frame arrives on both channels; each copy goes only to the
            # observers of the channel it came in on, so nobody sees it twice.
            if message.get("pattern") == _batch_channel(self._redis, "*"):
                batch_id = _batch_id_of(self._redis, message["channel"])
                self._broadcast(self._batch_channels, batch_id, frame)
            else:
                self._broadcast(self._channels, frame.task_id, frame)

    def _broadcast(
        self, registry: dict[str, set[asyncio.Queue]], key: str, frame: ProgressFrame
    ) -> None:
        # Synchronous on purpose: with no await inside, an observer detaching cannot change
        # the channel set mid-iteration.
        for channel in registry.get(key, ()):
            self._offer(channel, frame)

    @staticmethod
    def _offer(channel: asyncio.Queue, item) -> None:
        if channel.full():
            with suppress(asyncio.QueueEmpty):
                channel.get_nowait()
        with suppress(asyncio.QueueFull):
            channel.put_nowait(item)
