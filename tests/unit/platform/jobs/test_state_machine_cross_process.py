"""The template's behaviour once web and worker are separate processes.

Claiming, targeted writes, the DB-backed cancel flag, resume points stored on the
document, and the processing slot that is held from before the claim until the copy
phase ends. Uses the non-migration ``ReindexTaskModel`` so the template's genericity
stays proven.
"""

import asyncio

import pytest

from src.platform.jobs.task_model import TaskStatus
from tests.unit.platform.jobs.reindex import (
    LateCancelReindexStateMachine,
    RecordingSlotReindexStateMachine,
    ReindexStateMachine,
    ReindexTaskModel,
    UntilCancelledReindexStateMachine,
    drain,
    set_stored_fields,
)

pytestmark = pytest.mark.unit


class TestClaim:
    async def test_pending_task_runs_all_phases_after_being_claimed(self, reindex_task_factory):
        # Given a PENDING reindex task with no resume_from
        machine = ReindexStateMachine()
        task = await reindex_task_factory()

        # When run_task is called with its id
        await drain(machine, str(task.id))

        # Then processing, db update and cleanup each run once
        assert machine.phases_run == ["processing", "db", "fs"]
        # And the stored status is COMPLETED
        assert (await ReindexTaskModel.get(task.id)).status == TaskStatus.COMPLETED

    async def test_claim_resumes_from_the_phase_stored_on_the_document(self, reindex_task_factory):
        # Given a PENDING reindex task whose resume_from is UPDATING_DB
        machine = ReindexStateMachine()
        task = await reindex_task_factory(resume_from=TaskStatus.UPDATING_DB)

        # When run_task is called with its id
        await drain(machine, str(task.id))

        # Then processing is not run
        # And db update and cleanup each run once
        assert machine.phases_run == ["db", "fs"]

    async def test_task_that_is_no_longer_pending_is_not_run(self, reindex_task_factory):
        # Given a reindex task already PROCESSING (claimed by an earlier delivery)
        machine = ReindexStateMachine()
        task = await reindex_task_factory(status=TaskStatus.PROCESSING)

        # When run_task is called with its id
        frames = await drain(machine, str(task.id))

        # Then no phase runs and no frame is yielded
        assert machine.phases_run == []
        assert frames == []
        # And the stored status is still PROCESSING
        assert (await ReindexTaskModel.get(task.id)).status == TaskStatus.PROCESSING

    async def test_two_concurrent_deliveries_run_the_task_once(self, reindex_task_factory):
        # Given a PENDING reindex task
        machine = ReindexStateMachine()
        task = await reindex_task_factory()

        # When run_task is driven twice concurrently for the same id
        await asyncio.gather(drain(machine, str(task.id)), drain(machine, str(task.id)))

        # Then processing has run exactly once
        assert machine.phases_run.count("processing") == 1


class TestTargetedWrites:
    async def test_status_write_keeps_a_cancel_request_made_by_another_process(
        self, reindex_task_factory
    ):
        # Given a reindex task loaded into memory by the machine
        machine = ReindexStateMachine()
        created = await reindex_task_factory(status=TaskStatus.PROCESSING)
        in_memory = await ReindexTaskModel.get(created.id)
        # And another process sets cancel_requested=True on the stored document
        await set_stored_fields(created, cancel_requested=True)

        # When the machine writes a status change for that task
        await machine._update_task_status(in_memory, TaskStatus.PROCESS_DONE)

        # Then the stored document still has cancel_requested=True
        stored = await ReindexTaskModel.get(created.id)
        assert stored.cancel_requested is True
        assert stored.status == TaskStatus.PROCESS_DONE

    async def test_progress_flush_keeps_fields_it_does_not_own(self, reindex_task_factory):
        # Given a reindex task loaded into memory with index_name "books"
        machine = ReindexStateMachine(progress_flush_interval=0)
        created = await reindex_task_factory(status=TaskStatus.PROCESSING, index_name="books")
        in_memory = await ReindexTaskModel.get(created.id)
        # And another process changes the stored index_name to "films"
        await set_stored_fields(created, index_name="films")

        # When the machine flushes progress 7
        await machine._maybe_flush_progress(in_memory, 7)

        # Then the stored docs_indexed is 7
        stored = await ReindexTaskModel.get(created.id)
        assert stored.documents_done == 7
        # And the stored index_name is still "films"
        assert stored.index_name == "films"


class TestCancelFlag:
    async def test_cancel_requested_on_the_document_stops_a_running_task(
        self, reindex_task_factory
    ):
        # Given a PENDING reindex task whose processing loops until cancelled
        machine = UntilCancelledReindexStateMachine(progress_flush_interval=0.05)
        task = await reindex_task_factory()

        # When run_task is started
        run = asyncio.create_task(drain(machine, str(task.id)))
        await asyncio.sleep(0.1)
        # And another process sets cancel_requested=True on the stored document
        await set_stored_fields(task, cancel_requested=True)

        # Then the run ends within a few flush intervals
        await asyncio.wait_for(run, timeout=2)
        # And the stored status is CANCELLED
        assert (await ReindexTaskModel.get(task.id)).status == TaskStatus.CANCELLED


class TestRecoveryPlan:
    async def test_orphan_is_reset_to_pending_with_its_resume_point_stored(
        self, reindex_task_factory
    ):
        # Given a reindex task left in DB_UPDATED by a dead process
        task = await reindex_task_factory(status=TaskStatus.DB_UPDATED)

        # When plan_recovery runs
        planned = await ReindexStateMachine().plan_recovery()

        # Then the returned ids include that task
        assert planned == [str(task.id)]
        # And the stored status is PENDING with resume_from DELETING_SOURCE
        stored = await ReindexTaskModel.get(task.id)
        assert stored.status == TaskStatus.PENDING
        assert stored.resume_from == TaskStatus.DELETING_SOURCE

    async def test_pending_task_keeps_the_resume_point_a_retry_wrote(self, reindex_task_factory):
        # Given a PENDING reindex task whose resume_from is UPDATING_DB
        task = await reindex_task_factory(resume_from=TaskStatus.UPDATING_DB)

        # When plan_recovery runs
        planned = await ReindexStateMachine().plan_recovery()

        # Then the returned ids include that task
        assert planned == [str(task.id)]
        # And the stored resume_from is still UPDATING_DB
        assert (await ReindexTaskModel.get(task.id)).resume_from == TaskStatus.UPDATING_DB

    async def test_terminal_tasks_are_not_planned(self, reindex_task_factory):
        # Given reindex tasks in COMPLETED, FAILED and CANCELLED
        tasks = [
            await reindex_task_factory(status=status)
            for status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]

        # When plan_recovery runs
        planned = await ReindexStateMachine().plan_recovery()

        # Then none of them is returned and none of their statuses change
        assert planned == []
        for task in tasks:
            assert (await ReindexTaskModel.get(task.id)).status == task.status


class TestProcessingSlot:
    async def test_slot_is_held_from_before_the_claim_until_processing_ends(
        self, reindex_task_factory
    ):
        # Given a reindex machine whose processing slot records when it is entered and left
        machine = RecordingSlotReindexStateMachine()
        # And a PENDING reindex task
        task = await reindex_task_factory()

        # When run_task is driven to the end
        await drain(machine, str(task.id))

        # Then the recorded order is: slot entered, task claimed, processing, slot left, db update, cleanup
        assert machine.status_when_slot_entered == TaskStatus.PENDING
        assert machine.events == ["slot entered", "processing", "slot left", "db", "fs"]

    async def test_task_resuming_after_processing_takes_no_slot(self, reindex_task_factory):
        # Given a reindex machine with a recording processing slot
        machine = RecordingSlotReindexStateMachine()
        # And a PENDING reindex task whose resume_from is UPDATING_DB
        task = await reindex_task_factory(resume_from=TaskStatus.UPDATING_DB)

        # When run_task is driven to the end
        await drain(machine, str(task.id))

        # Then the slot was never entered
        assert machine.events == ["db", "fs"]

    async def test_slot_is_released_when_the_claim_misses(self, reindex_task_factory):
        # Given a reindex machine whose slot blocks until released by the test
        machine = RecordingSlotReindexStateMachine()
        machine.gate.clear()
        # And a PENDING reindex task
        task = await reindex_task_factory()

        # When run_task is started and waits on the slot
        run = asyncio.create_task(drain(machine, str(task.id)))
        await asyncio.wait_for(machine.waiting.wait(), timeout=2)
        # And another process moves the stored task to CANCELLED
        await set_stored_fields(task, status=TaskStatus.CANCELLED.value)
        # And the slot is let through
        machine.gate.set()
        await asyncio.wait_for(run, timeout=2)

        # Then the slot is left again and no phase runs
        assert machine.events == ["slot entered", "slot left"]

    async def test_slot_is_released_when_processing_fails(self, reindex_task_factory):
        # Given a reindex machine with a recording processing slot
        machine = RecordingSlotReindexStateMachine(fail_in="processing")
        # And a PENDING reindex task whose processing raises
        task = await reindex_task_factory()

        # When run_task is driven to the end
        await drain(machine, str(task.id))

        # Then the slot was left
        assert machine.events == ["slot entered", "processing", "slot left"]
        # And the stored status is FAILED with failed_step PROCESSING
        stored = await ReindexTaskModel.get(task.id)
        assert stored.status == TaskStatus.FAILED
        assert stored.failed_step == TaskStatus.PROCESSING.value


class TestDeliveryWhileAlreadyHeld:
    """A task can wait a long time for its slot while still PENDING, and reconciliation
    re-sends exactly such tasks. A second delivery must not become a second waiter."""

    # Scenario: a redelivery of a task waiting for its slot does not wait too
    #   Given a reindex machine whose processing slot blocks until released by the test
    #   And a PENDING reindex task whose first delivery is waiting on that slot
    #   When a second delivery of the same task id is run
    #   Then the second delivery ends at once, without yielding a frame
    #   And it never waits on the slot
    #   And once the slot is let through, processing runs exactly once
    async def test_redelivery_of_a_task_waiting_for_its_slot_ends_at_once(
        self, reindex_task_factory
    ):
        machine = RecordingSlotReindexStateMachine()
        machine.gate.clear()
        task = await reindex_task_factory()
        first = asyncio.create_task(drain(machine, str(task.id)))
        await asyncio.wait_for(machine.waiting.wait(), timeout=2)

        # The slot is still closed: a redelivery that queued for it would never return.
        second_frames = await asyncio.wait_for(drain(machine, str(task.id)), timeout=2)

        assert second_frames == []
        machine.gate.set()
        await asyncio.wait_for(first, timeout=2)
        assert machine.events.count("slot entered") == 1
        assert machine.phases_run.count("processing") == 1

    # Scenario: a finished run no longer holds the task
    #   Given a reindex task whose processing failed in an earlier run on this machine
    #   And the stored task has since been reset to PENDING, as a retry does
    #   When the task is delivered again
    #   Then it runs through all phases to COMPLETED
    async def test_task_delivered_again_after_its_run_ended_is_run(self, reindex_task_factory):
        machine = ReindexStateMachine(fail_in="processing")
        task = await reindex_task_factory()
        await drain(machine, str(task.id))
        assert (await ReindexTaskModel.get(task.id)).status == TaskStatus.FAILED

        await set_stored_fields(
            task, status=TaskStatus.PENDING.value, resume_from=TaskStatus.PROCESSING.value
        )
        machine.fail_in = None
        await drain(machine, str(task.id))

        assert (await ReindexTaskModel.get(task.id)).status == TaskStatus.COMPLETED
        assert machine.phases_run == ["processing", "processing", "db", "fs"]


class TestFinishingProcessing:
    """A cancel can be accepted while the work is in its last moments, after the last
    point the phase looks at the flag. Finishing the phase and accepting a cancel are
    both conditional writes on the document, so exactly one of them takes effect."""

    # Scenario: a cancel stored before the phase finishes wins
    #   Given a reindex machine whose processing finishes through _finish_processing
    #   And another process stores cancel_requested on the task after its last flag check
    #   When run_task is driven to the end
    #   Then _finish_processing reports that the cancel came first
    #   And the stored status is CANCELLED
    #   And neither the db update nor the cleanup phase runs
    async def test_cancel_stored_before_processing_finishes_wins(self, reindex_task_factory):
        machine = LateCancelReindexStateMachine(cancel_late=True)
        task = await reindex_task_factory()

        await drain(machine, str(task.id))

        assert machine.finished is False
        assert (await ReindexTaskModel.get(task.id)).status == TaskStatus.CANCELLED
        assert machine.phases_run == ["processing"]

    # Scenario: with no cancel, finishing moves the task on
    #   Given a reindex machine whose processing finishes through _finish_processing
    #   And no cancel is requested
    #   When run_task is driven to the end
    #   Then the db update and cleanup phases run
    #   And the stored status is COMPLETED
    async def test_processing_finished_without_a_cancel_moves_on(self, reindex_task_factory):
        machine = LateCancelReindexStateMachine()
        task = await reindex_task_factory()

        await drain(machine, str(task.id))

        assert machine.finished is True
        assert machine.phases_run == ["processing", "db", "fs"]
        stored = await ReindexTaskModel.get(task.id)
        assert stored.status == TaskStatus.COMPLETED
        assert stored.documents_done == stored.documents_total
