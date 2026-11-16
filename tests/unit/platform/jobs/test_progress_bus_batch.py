"""Progress for a batch of tasks: frames published once more on the batch's channel, and
observers that follow a whole batch rather than one task.

Runs against the real Redis testcontainer. The batch summary is opaque to the bus; the
tests hand it a stand-in summarizer and a settled-check.
"""

import asyncio
import json

import pytest

from src.platform.jobs.task_model import TaskStatus
from tests.unit.platform.jobs.test_progress_bus import (  # noqa: F401  (fixtures)
    _frame,
    _rest,
    _Snapshots,
    bus_factory,
    prefix,
    publisher,
    redis,
)

pytestmark = pytest.mark.unit


class _Summaries:
    """A stand-in for the batch summary lookup: returns whatever the test sets."""

    def __init__(self, value: dict | None):
        self.value = value

    async def __call__(self, batch_id: str) -> dict | None:
        return self.value


def _settled(summary: dict) -> bool:
    return summary["active"] == 0


async def _next(stream, timeout: float = 2.0):
    return await asyncio.wait_for(anext(stream), timeout)


async def _messages(pubsub, window: float = 0.5) -> list[dict]:
    """Everything delivered within ``window`` seconds. A filtered subscribe confirmation
    reads as None too, so a None does not mean the stream is drained."""
    received = []
    deadline = asyncio.get_running_loop().time() + window
    while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
        message = await pubsub.get_message(timeout=remaining)
        if message is not None:
            received.append(json.loads(message["data"]))
    return received


class TestPublishingForABatch:
    async def test_frame_published_with_a_batch_id_reaches_the_batch_channel(
        self, redis, prefix, publisher,
    ):
        """
        Scenario: a child's frame goes to its task channel and to its batch channel
          Given a subscriber to channel "pfx:batch:B:progress"
          And a subscriber to channel "pfx:task:t1:progress"
          When a PROCESSING frame for task "t1" is published with batch id "B"
          Then both subscribers receive that frame
        """
        batch_sub = redis.pubsub(ignore_subscribe_messages=True)
        task_sub = redis.pubsub(ignore_subscribe_messages=True)
        await batch_sub.subscribe(f"{prefix}:batch:B:progress")
        await task_sub.subscribe(f"{prefix}:task:t1:progress")
        try:
            await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 40), batch_id="B")

            for received in (await _messages(batch_sub), await _messages(task_sub)):
                assert [(m["task_id"], m["status"], m["current"]) for m in received] == [
                    ("t1", "PROCESSING", 40)
                ]
        finally:
            await batch_sub.aclose()
            await task_sub.aclose()

    async def test_frame_published_without_a_batch_id_reaches_no_batch_channel(
        self, redis, prefix, publisher,
    ):
        """
        Scenario: a task outside any batch publishes as before
          Given a subscriber to pattern "pfx:batch:*:progress"
          When a PROCESSING frame for task "t1" is published without a batch id
          Then the batch subscriber receives nothing
        """
        batch_sub = redis.pubsub(ignore_subscribe_messages=True)
        await batch_sub.psubscribe(f"{prefix}:batch:*:progress")
        try:
            await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 40))

            assert await _messages(batch_sub) == []
        finally:
            await batch_sub.aclose()


class TestObservingABatch:
    async def test_opens_with_the_summary(self, bus_factory):
        """
        Scenario: an observer first learns where the batch stands
          Given a summarizer that reports batch "B" as 3 children with 3 active
          When batch "B" is observed
          Then the first event carries that summary and no frame
        """
        bus = await bus_factory()
        summary = {"total": 3, "active": 3}

        stream = bus.observe_batch("B", _Summaries(summary), _settled)
        try:
            opening = await _next(stream)
        finally:
            await stream.aclose()

        assert opening.summary == summary
        assert opening.frame is None

    async def test_forwards_child_frames(self, bus_factory, publisher):
        """
        Scenario: frames of the batch's children are relayed as they arrive
          Given an observer of batch "B" that has received its opening summary
          When PROCESSING frames for children "t1" and then "t2" are published with batch id "B"
          Then the observer receives events carrying those two frames, in order
          And neither event carries a summary
        """
        bus = await bus_factory()
        stream = bus.observe_batch("B", _Summaries({"total": 2, "active": 2}), _settled)
        try:
            await _next(stream)

            await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 10), batch_id="B")
            await publisher.publish(_frame("t2", TaskStatus.PROCESSING, 20), batch_id="B")
            events = [await _next(stream), await _next(stream)]
        finally:
            await stream.aclose()

        assert [(e.frame.task_id, e.frame.current) for e in events] == [("t1", 10), ("t2", 20)]
        assert [e.summary for e in events] == [None, None]

    async def test_does_not_forward_frames_of_another_batch(self, bus_factory, publisher):
        """
        Scenario: an observer only hears its own batch
          Given an observer of batch "B1"
          When a PROCESSING frame for task "t9" is published with batch id "B2"
          Then the observer of "B1" receives no event for it
        """
        bus = await bus_factory()
        stream = bus.observe_batch("B1", _Summaries({"total": 1, "active": 1}), _settled)
        try:
            await _next(stream)

            await publisher.publish(_frame("t9", TaskStatus.PROCESSING, 90), batch_id="B2")
            await publisher.publish(_frame("t1", TaskStatus.PROCESSING, 10), batch_id="B1")
            event = await _next(stream)
        finally:
            await stream.aclose()

        assert event.frame.task_id == "t1"

    async def test_a_terminal_child_frame_comes_with_a_fresh_summary(self, bus_factory, publisher):
        """
        Scenario: when a child ends the observer gets the new counts with it
          Given an observer of batch "B" whose summarizer now reports 1 of 2 children completed
          When a COMPLETED frame for child "t1" is published with batch id "B"
          Then the observer receives one event carrying that frame and the fresh summary
        """
        bus = await bus_factory()
        summaries = _Summaries({"total": 2, "active": 2, "completed": 0})
        stream = bus.observe_batch("B", summaries, _settled)
        try:
            await _next(stream)
            summaries.value = {"total": 2, "active": 1, "completed": 1}

            await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100), batch_id="B")
            event = await _next(stream)
        finally:
            await stream.aclose()

        assert (event.frame.task_id, event.frame.status) == ("t1", "COMPLETED")
        assert event.summary == {"total": 2, "active": 1, "completed": 1}

    async def test_ends_once_the_summary_is_settled(self, bus_factory, publisher):
        """
        Scenario: the stream ends with the batch
          Given an observer of batch "B"
          And the summarizer reports every child ended once "t2" completes
          When a COMPLETED frame for the last child "t2" is published with batch id "B"
          Then the observer's stream ends after that event
        """
        bus = await bus_factory()
        summaries = _Summaries({"total": 2, "active": 1})
        stream = bus.observe_batch("B", summaries, _settled)
        await _next(stream)
        summaries.value = {"total": 2, "active": 0}

        await publisher.publish(_frame("t2", TaskStatus.COMPLETED, 100), batch_id="B")
        rest = await _rest(stream)

        assert [(e.frame.task_id, e.summary) for e in rest] == [("t2", {"total": 2, "active": 0})]

    async def test_an_already_settled_batch_ends_after_its_summary(self, bus_factory):
        """
        Scenario: observing a batch that has already ended
          Given a summarizer that reports batch "B" as settled
          When batch "B" is observed
          Then exactly one event is received, carrying that summary
          And the stream ends
        """
        bus = await bus_factory()

        events = await _rest(bus.observe_batch("B", _Summaries({"total": 2, "active": 0}), _settled))

        assert [(e.summary, e.frame) for e in events] == [({"total": 2, "active": 0}, None)]

    async def test_an_unknown_batch_yields_nothing(self, bus_factory):
        """
        Scenario: observing a batch that does not exist
          Given a summarizer that returns None for batch "B"
          When batch "B" is observed
          Then the stream ends without any event
        """
        bus = await bus_factory()

        assert await _rest(bus.observe_batch("B", _Summaries(None), _settled)) == []

    async def test_watchdog_ends_a_batch_whose_last_child_sent_no_frame(self, bus_factory):
        """
        Scenario: a child settled with no frame — cancelled while queued, or its worker
          died — still lets the observer finish
          Given a bus with a watchdog interval of 0.1 seconds
          And an observer of batch "B" whose summarizer starts reporting it settled
            without any frame being published
          When the watchdog interval passes
          Then the observer receives an event carrying the settled summary
          And the stream ends
        """
        bus = await bus_factory(watchdog_interval=0.1)
        summaries = _Summaries({"total": 1, "active": 1})
        stream = bus.observe_batch("B", summaries, _settled)
        await _next(stream)
        summaries.value = {"total": 1, "active": 0}

        rest = await _rest(stream)

        assert [(e.summary, e.frame) for e in rest] == [({"total": 1, "active": 0}, None)]

    async def test_a_task_observer_sees_a_batch_child_frame_once(self, bus_factory, publisher):
        """
        Scenario: a child's frame travels on two channels but reaches a task observer once
          Given an observer of task "t1"
          When a COMPLETED frame for "t1" is published with batch id "B"
          Then the task observer receives exactly one frame
        """
        bus = await bus_factory()
        stream = bus.observe("t1", _Snapshots(_frame("t1", TaskStatus.PROCESSING, 10)))
        await _next(stream)

        await publisher.publish(_frame("t1", TaskStatus.COMPLETED, 100), batch_id="B")
        rest = await _rest(stream)

        assert [(f.task_id, f.status) for f in rest] == [("t1", "COMPLETED")]
