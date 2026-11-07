import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict
import json

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.logger import get_logger
from src.platform.jobs.progress import ProgressFrame
from src.platform.jobs.state_machine import TaskStateMachine

logger = get_logger("progress_bus")

#: Seconds the latest frame outlives its task's last report. Long enough for a client
#: that reconnects mid-task; short enough that nothing has to clean it up.
LATEST_FRAME_TTL = 60

#: Looks up a task's stored state, for observers that have no live frame to start from.
SnapshotFn = Callable[[str], Awaitable[ProgressFrame | None]]

_END_OF_STREAM = object()


def _progress_channel(prefix: str, task_id: str) -> str:
    return f"{prefix}:task:{task_id}:progress"


def _latest_key(prefix: str, task_id: str) -> str:
    return f"{prefix}:task:{task_id}:latest"


def _encode(frame: ProgressFrame) -> str:
    return json.dumps(asdict(frame))


def _decode(raw: str | bytes) -> ProgressFrame:
    return ProgressFrame(**json.loads(raw))


def _is_terminal(frame: ProgressFrame) -> bool:
    return frame.status in TaskStateMachine.TERMINAL_STATUSES


class ProgressPublisher:
    """
    The worker's side of the bus: sends each frame a task produces to whoever is watching.

    Every frame is published on the task's channel and also stored as the task's latest
    frame, so an observer that attaches between two frames still opens with fresh numbers
    rather than with the database's throttled copy.
    """

    def __init__(self, redis: Redis, prefix: str):
        """
        :param redis: Client for the Redis the web process subscribes to.
        :type redis: Redis
        :param prefix: Key prefix shared with the web process, e.g. ``"video-app"``.
        :type prefix: str
        """
        self._redis = redis
        self._prefix = prefix

    async def publish(self, frame: ProgressFrame) -> None:
        """
        Send one frame to the task's observers.

        A Redis failure is logged and swallowed. Progress is advisory: a migration must
        not fail because nobody could be told how far it got, and observers fall back to
        the database once frames stop arriving.

        :param frame: The frame to deliver.
        :type frame: ProgressFrame
        :rtype: None
        """
        payload = _encode(frame)
        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.publish(_progress_channel(self._prefix, frame.task_id), payload)
                pipe.set(_latest_key(self._prefix, frame.task_id), payload, ex=LATEST_FRAME_TTL)
                await pipe.execute()
        except (RedisError, OSError) as e:
            logger.warning(f"Could not publish progress for task {frame.task_id}: {e}")

    async def relay(self, frames: AsyncIterable[ProgressFrame]) -> None:
        """
        Publish every frame of a run, as it is produced.

        :param frames: The frames a state machine yields for one run.
        :type frames: AsyncIterable[ProgressFrame]
        :rtype: None
        """
        async for frame in frames:
            await self.publish(frame)


class ProgressBus:
    """
    The web process's side of the bus: one Redis subscription, fanned out to every client
    watching a task.

    A single pattern subscription covers every task, so attaching an observer never costs
    a Redis round trip of its own and there is no subscribe/unsubscribe race to get wrong.
    Frames for tasks nobody watches are simply dropped.

    Each observer gets its own bounded channel. A full channel drops its oldest frame:
    clients only care about the newest numbers, and a slow browser must never hold up the
    reader every other observer depends on.
    """

    def __init__(
        self,
        redis: Redis,
        prefix: str,
        watchdog_interval: float = 10.0,
        channel_size: int = 64,
    ):
        """
        :param redis: Client for the Redis the workers publish to.
        :type redis: Redis
        :param prefix: Key prefix shared with the workers.
        :type prefix: str
        :param watchdog_interval: Seconds without a frame after which an observer checks
            the database. A worker that crashes, or a task cancelled before it ever ran,
            sends no final frame; without this the observer would wait forever.
        :type watchdog_interval: float
        :param channel_size: Frames buffered per observer before the oldest is dropped.
        :type channel_size: int
        """
        self._redis = redis
        self._prefix = prefix
        self._watchdog_interval = watchdog_interval
        self._channel_size = channel_size

        self._channels: dict[str, set[asyncio.Queue]] = {}
        self._pubsub = None
        self._reader: asyncio.Task | None = None

    async def start(self) -> None:
        """
        Subscribe and start delivering frames. Returns once the subscription is in place,
        so a frame published afterwards is guaranteed to arrive.

        :rtype: None
        """
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await self._pubsub.psubscribe(_progress_channel(self._prefix, "*"))
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
        for channels in self._channels.values():
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
            channels = self._channels.get(task_id)
            if channels is not None:
                channels.discard(channel)
                if not channels:
                    self._channels.pop(task_id, None)

    async def _read_latest(self, task_id: str) -> ProgressFrame | None:
        try:
            raw = await self._redis.get(_latest_key(self._prefix, task_id))
        except (RedisError, OSError) as e:
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
            except (RedisError, OSError) as e:
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
            self._broadcast(frame)

    def _broadcast(self, frame: ProgressFrame) -> None:
        # Synchronous on purpose: with no await inside, an observer detaching cannot change
        # the channel set mid-iteration.
        for channel in self._channels.get(frame.task_id, ()):
            self._offer(channel, frame)

    @staticmethod
    def _offer(channel: asyncio.Queue, item) -> None:
        if channel.full():
            with suppress(asyncio.QueueEmpty):
                channel.get_nowait()
        with suppress(asyncio.QueueFull):
            channel.put_nowait(item)
