from abc import ABC, abstractmethod
import asyncio
from contextlib import AbstractAsyncContextManager, AsyncExitStack, nullcontext
from time import time
from typing import Any, AsyncGenerator, Generic, TypeVar

from beanie.operators import NE, Set
from bson import ObjectId

from src.logger import get_logger
from src.platform.jobs.progress import ProgressFrame
from src.platform.jobs.task_model import BaseTaskModel, TaskStatus

logger = get_logger("task_state_machine")

TTask = TypeVar("TTask", bound=BaseTaskModel)


class TaskStateMachine(ABC, Generic[TTask]):
    """
    Lifecycle template for a background task that runs in three phases.

    The phases are deliberately coarse, because they are the ones that decide how far a
    crashed task has to be rewound:

    1. ``PROCESSING`` — do the actual work, reporting progress as it goes.
    2. ``UPDATING_DB`` — make the database reflect the result.
    3. ``DELETING_SOURCE`` — settle the outside world, e.g. remove what the work replaced.

    A task type that has nothing to do in a phase implements it as a no-op; the ordering
    and the crash-recovery matrix still hold. What the template owns is *when* phases run,
    how failure is distinguished from shutdown, and how progress is throttled to the
    database. What it deliberately knows nothing about is the work itself — no storage, no
    paths, no particular document class.

    Subclasses bind their document type by declaring ``task_model``::

        class ReindexStateMachine(TaskStateMachine[ReindexTaskModel]):
            task_model = ReindexTaskModel
    """

    #: Document class this machine drives. Every subclass must set it.
    task_model: type[TTask]

    _PHASE_ORDER = [TaskStatus.PROCESSING, TaskStatus.UPDATING_DB, TaskStatus.DELETING_SOURCE]
    TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}

    # Where a task interrupted mid-flight should resume from, given the status it died in.
    # Phases that may have left partial side effects resume at their own start and rely on
    # _compensate_before_resume to undo them first.
    _RESUME_POINT_BY_STATUS = {
        TaskStatus.PENDING: TaskStatus.PROCESSING,
        TaskStatus.PROCESSING: TaskStatus.PROCESSING,
        TaskStatus.PROCESS_DONE: TaskStatus.UPDATING_DB,
        TaskStatus.UPDATING_DB: TaskStatus.UPDATING_DB,
        TaskStatus.DB_UPDATED: TaskStatus.DELETING_SOURCE,
        TaskStatus.DELETING_SOURCE: TaskStatus.DELETING_SOURCE,
    }

    def __init__(self, progress_flush_interval: float = 3.0):
        self._progress_flush_interval = progress_flush_interval

        # task_id -> True once someone asked for this task to stop.
        self._cancel_requested: dict[str, bool] = {}
        # task_id -> timestamp of the last progress write, for throttling.
        self._last_flush_at: dict[str, float] = {}
        # Tasks this process is running or waiting to run. A task waits for its slot while
        # still PENDING, which is exactly what reconciliation re-sends; without this every
        # re-send would queue up as one more waiter.
        self._in_flight: set[str] = set()

    # ------------------------------------------------------------------
    # Runner-facing API
    # ------------------------------------------------------------------

    async def run_task(self, task_id: str) -> AsyncGenerator[ProgressFrame, None]:
        """
        Claim a PENDING task and execute it, yielding a progress frame at every notable step.

        Called by the worker for every message on its queue. The message carries only the
        id; where to resume comes from the task's stored ``resume_from``. Deliberately
        forgiving: a task that has vanished, already settled or been claimed by an earlier
        delivery produces no frames rather than raising, so a duplicate or stale message
        can never crash a worker.

        A delivery for a task this process already holds ends at once, so redeliveries
        never pile up as waiters behind a busy slot. One worker process per queue is what
        makes a per-process record enough.

        When the run starts with the processing phase, the slot from ``_processing_slot``
        is taken *before* the claim and given back as soon as processing ends. Waiting for
        it therefore happens while the task still reads PENDING, so the task list shows
        "queued" and a cancel takes the cheap PENDING path.

        :param task_id: String form of the task's ObjectId.
        :type task_id: str
        :yield: Progress frames, ending with a terminal-status frame on failure or
            cancellation.
        :rtype: AsyncGenerator[ProgressFrame, None]
        """
        if task_id in self._in_flight:
            logger.info(f"Task {task_id} is already held by this worker; dropping this delivery")
            return
        self._in_flight.add(task_id)
        slot = AsyncExitStack()
        try:
            task = await self.task_model.get(ObjectId(task_id))
            if task is None:
                logger.warning(f"Task {task_id} no longer exists, skipping execution")
                return
            if task.status != TaskStatus.PENDING:
                logger.info(f"Task {task_id} is {task.status}, not PENDING; skipping this delivery")
                return

            start_from = self._resume_point_of(task)
            if self._should_run_phase(start_from, TaskStatus.PROCESSING):
                await slot.enter_async_context(self._processing_slot(task))
            if not await self._claim(task, start_from):
                logger.info(f"Task {task_id} was settled or claimed elsewhere; skipping")
                return
            async for progress in self._run_state_machine(task, start_from, slot):
                yield progress
        finally:
            await slot.aclose()
            self._in_flight.discard(task_id)
            self._last_flush_at.pop(task_id, None)
            self._cancel_requested.pop(task_id, None)

    async def build_snapshot(self, task_id: str) -> ProgressFrame | None:
        """
        Build a progress frame from persisted state.

        Used by observers when no live frame is available — for example right after a
        worker restart, or for a task that finished long ago.

        :param task_id: String form of the task's ObjectId.
        :type task_id: str
        :return: A frame describing the task's stored state, or None if it no longer exists.
        :rtype: ProgressFrame | None
        """
        task = await self.task_model.get(ObjectId(task_id))
        if task is None:
            return None
        return self._make_progress(task)

    async def plan_recovery(self) -> list[str]:
        """
        Get every unfinished task of this type ready to be delivered again.

        Run once when this type's worker starts. With exactly one worker process per queue,
        any task left mid-phase must have been abandoned by that worker's previous run.
        Each one is mapped through ``_RESUME_POINT_BY_STATUS``, given a chance to undo its
        partial side effects via ``_compensate_before_resume``, and stored back as PENDING
        with the resume point in ``resume_from``, so the task list shows it as queued
        rather than falsely running.

        PENDING tasks are returned untouched: their message may have been lost with Redis,
        and their ``resume_from`` may have been written by a retry that must not be undone.

        :return: Ids of the tasks to deliver again.
        :rtype: list[str]
        """
        active_statuses = [
            s.value for s in TaskStatus if s not in TaskStateMachine.TERMINAL_STATUSES
        ]
        unfinished = await self.task_model.find({"status": {"$in": active_statuses}}).to_list()

        planned: list[str] = []
        for task in unfinished:
            status = TaskStatus(task.status)
            if status == TaskStatus.PENDING:
                planned.append(str(task.id))
                continue

            start_from = TaskStateMachine._RESUME_POINT_BY_STATUS[status]
            before = self._dump(task)
            try:
                await self._compensate_before_resume(task, start_from)
            except Exception as e:
                logger.warning(f"Task {task.id}: compensation before resume failed: {e}")

            model = self.task_model
            await task.set({
                **self._changed_fields(before, task),
                model.status: TaskStatus.PENDING,
                model.resume_from: start_from,
                model.updated_at: time(),
            })
            logger.info(f"Recovering task {task.id}: {status} -> resume from {start_from}")
            planned.append(str(task.id))

        return planned

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    async def _run_state_machine(
        self,
        task: TTask,
        start_from: TaskStatus,
        processing_slot: AsyncExitStack,
    ) -> AsyncGenerator[ProgressFrame, None]:
        """
        Drive the three phases in order, skipping any that precede ``start_from``.

        Failure handling differs by cause, and the distinction matters:

        * ``CancelledError`` (process shutting down) — the persisted status is left
          untouched and the error re-raised, so ``plan_recovery`` picks the task up on
          the next startup.
        * Any other exception — the task is marked FAILED with ``failed_step`` set to
          the phase that broke, which is what lets a later retry resume from there.

        :param task: The task document, already loaded and known to be non-terminal.
        :type task: TTask
        :param start_from: First phase to execute.
        :type start_from: TaskStatus
        :param processing_slot: Holds the slot taken for the processing phase; closed as
            soon as that phase ends, so the later phases never keep another task waiting.
        :type processing_slot: AsyncExitStack
        :yield: Progress frames from each phase.
        :rtype: AsyncGenerator[ProgressFrame, None]
        :raises asyncio.CancelledError: Propagated on shutdown so the worker can stop.
        """
        try:
            if self._should_run_phase(start_from, TaskStatus.PROCESSING):
                try:
                    async for progress in self._execute_processing(task):
                        yield progress
                finally:
                    await processing_slot.aclose()
                if task.status == TaskStatus.CANCELLED:
                    return

            if self._should_run_phase(start_from, TaskStatus.UPDATING_DB):
                await self._execute_db_update(task)
                yield self._make_progress(task, message="Database updated")

            if self._should_run_phase(start_from, TaskStatus.DELETING_SOURCE):
                warning = await self._execute_fs_cleanup(task)
                yield self._make_progress(task, message=warning or "Task completed")

        except asyncio.CancelledError:
            # Process is shutting down. Leave the persisted status alone so that
            # plan_recovery() can resume this task on the next startup.
            logger.info(f"Task {task.id} interrupted at {task.status}, will recover on restart")
            raise

        except Exception as e:
            logger.exception(f"Task {task.id} failed: {e}")
            failed_step = (
                task.status
                if task.status not in TaskStateMachine.TERMINAL_STATUSES
                else TaskStatus.PROCESSING
            )
            await self._update_task_status(
                task,
                TaskStatus.FAILED,
                error_message=str(e),
                failed_step=TaskStatus(failed_step).value,
            )
            yield self._make_progress(task, message=f"Task failed: {e}")

    @staticmethod
    def _should_run_phase(start_from: TaskStatus, phase: TaskStatus) -> bool:
        """
        Decide whether a phase is at or after the resume point.

        Statuses that are not phases themselves (PROCESS_DONE, DB_UPDATED, ...) fall back
        to position 0, so an unmapped ``start_from`` conservatively runs everything.

        :param start_from: The phase execution should resume at.
        :type start_from: TaskStatus
        :param phase: The phase being considered.
        :type phase: TaskStatus
        :return: True if ``phase`` should run.
        :rtype: bool
        """
        order = {s: i for i, s in enumerate(TaskStateMachine._PHASE_ORDER)}
        return order.get(phase, 0) >= order.get(start_from, 0)

    # ------------------------------------------------------------------
    # Phases — implemented per task type
    # ------------------------------------------------------------------

    @abstractmethod
    async def _execute_processing(self, task: TTask) -> AsyncGenerator[ProgressFrame, None]:
        """
        Phase 1 — do the work, reporting progress as it goes.

        Implementations must poll ``_cancel_requested`` if they can run for a long time,
        and report through ``_maybe_flush_progress`` as they go — that write is what
        carries a cancel request from the web process into ``_cancel_requested``. They end
        through ``_finish_processing``, which catches a cancel accepted after the last poll. They
        must also undo their partial side effects before propagating an error, since this
        phase always restarts from the beginning on both retry and crash recovery.

        :param task: The task being executed.
        :type task: TTask
        :yield: Progress frames while the work is in flight.
        :rtype: AsyncGenerator[ProgressFrame, None]
        """
        ...

    @abstractmethod
    async def _execute_db_update(self, task: TTask) -> None:
        """
        Phase 2 — make the database reflect the completed work.

        Must be idempotent: recovery may run this phase again after it already succeeded,
        so implementations have to detect and tolerate work that is already done.

        :param task: The task being executed.
        :type task: TTask
        :rtype: None
        """
        ...

    @abstractmethod
    async def _execute_fs_cleanup(self, task: TTask) -> str | None:
        """
        Phase 3 — settle the outside world and finish the task.

        Failures here are reported rather than raised: by this point the work is done and
        the database already records it, so a leftover file or a stale aggregate is worth a
        warning, not a failure. Implementations end by marking the task COMPLETED.

        A task type with nothing to clean up implements this as ``return None``.

        :param task: The task being executed.
        :type task: TTask
        :return: A warning to surface to the user, or None if everything went cleanly.
        :rtype: str | None
        """
        ...

    async def _compensate_before_resume(self, task: TTask, start_from: TaskStatus) -> None:
        """
        Undo the partial side effects of an interrupted phase, before it is re-run.

        Called by ``plan_recovery`` for every task being resumed, and available to retry
        paths that rewind a task the same way. The default does nothing, which is correct
        for any task whose phases leave nothing behind when they die halfway.

        Exceptions are logged and swallowed by the caller: a task that cannot be tidied up
        should still be recovered rather than stranded.

        :param task: The task about to be re-queued.
        :type task: TTask
        :param start_from: The phase it will resume at.
        :type start_from: TaskStatus
        :rtype: None
        """
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _processing_slot(self, task: TTask) -> AbstractAsyncContextManager[Any]:
        """
        What a task must hold while its processing phase runs.

        Entered before the claim and left when processing ends (see ``run_task``). The
        default holds nothing; a task type whose work competes for a scarce resource —
        a disk, a CPU budget — returns a context manager that waits for its share.

        :param task: The PENDING task about to be claimed.
        :type task: TTask
        :return: An async context manager guarding the processing phase.
        :rtype: AbstractAsyncContextManager
        """
        return nullcontext()

    @staticmethod
    def _resume_point_of(task: TTask) -> TaskStatus:
        """
        The phase a PENDING task should start at, read from its stored ``resume_from``.

        :param task: The task about to be claimed.
        :type task: TTask
        :return: The stored resume point, or PROCESSING when absent or unparsable.
        :rtype: TaskStatus
        """
        if not task.resume_from:
            return TaskStatus.PROCESSING
        try:
            return TaskStatus(task.resume_from)
        except ValueError:
            logger.warning(f"Task {task.id} has unparsable resume_from '{task.resume_from}'")
            return TaskStatus.PROCESSING

    async def _claim(self, task: TTask, start_from: TaskStatus) -> bool:
        """
        Atomically move a PENDING task into the phase it starts at.

        The status condition is what makes a duplicate delivery, a task cancelled while it
        waited for a slot, and a race between two deliveries all resolve to "run once".

        :param task: The task, updated in place when the claim succeeds.
        :type task: TTask
        :param start_from: The phase the task starts at.
        :type start_from: TaskStatus
        :return: True if this caller now owns the run.
        :rtype: bool
        """
        model = self.task_model
        now = time()
        claimed = await model.find_one(
            model.id == task.id, model.status == TaskStatus.PENDING
        ).update(Set({model.status: start_from, model.updated_at: now}))
        if not claimed.matched_count:
            return False
        task.status = start_from
        task.updated_at = now
        return True

    async def _update_task_status(self, task: TTask, status: TaskStatus, **extra_fields) -> None:
        """
        Move the task to a new status and persist it, stamping ``completed_at`` on
        terminal statuses.

        Only the fields named here are written. The web process writes to the same
        document — ``cancel_requested`` above all — and a whole-document save from this
        process's stale copy would silently undo it.

        :param task: The task document to update in place.
        :type task: TTask
        :param status: The status to move to.
        :type status: TaskStatus
        :param extra_fields: Additional document fields to set in the same write, e.g.
            ``error_message`` or ``failed_step``.
        :rtype: None
        """
        fields: dict[str, Any] = {"status": TaskStatus(status), "updated_at": time()}
        if status in TaskStateMachine.TERMINAL_STATUSES:
            fields["completed_at"] = time()
        fields.update(extra_fields)
        await task.set(fields)
        task.status = status

    async def _finish_processing(self, task: TTask, **fields: Any) -> bool:
        """
        Move a task from PROCESSING to PROCESS_DONE, unless a cancel was accepted first.

        The processing phase only looks at the cancel flag between steps, so a cancel can
        be accepted after its last look — while the last chunk of a copy is written. The
        web process raises the flag only on a PROCESSING task, and this write only lands
        on a task without the flag, so exactly one of the two takes effect: the task is
        cancelled, or the cancel is refused as too late. Never both, which would tell the
        user "cancelled" about work that went on to complete.

        :param task: The task whose processing just succeeded; updated in place.
        :type task: TTask
        :param fields: Further fields to set with the transition, e.g. the final progress.
        :return: True if the task moved on. False if a cancel came first: the caller must
            undo the phase's work and settle the task as CANCELLED.
        :rtype: bool
        """
        model = self.task_model
        now = time()
        moved = await model.find_one(
            model.id == task.id,
            model.status == TaskStatus.PROCESSING,
            NE(model.cancel_requested, True),
        ).update(Set({model.status: TaskStatus.PROCESS_DONE, model.updated_at: now, **fields}))
        if not moved.matched_count:
            return False
        task.status = TaskStatus.PROCESS_DONE
        task.updated_at = now
        for key, value in fields.items():
            setattr(task, key, value)
        return True

    async def _maybe_flush_progress(self, task: TTask, current: int) -> None:
        """
        Persist progress, at most once per ``progress_flush_interval``, and pick up a
        cancel request on the way back.

        Throttled because a running phase reports far more often than the database needs to
        know. ``Document.set`` refreshes the task from the stored document in the same round
        trip, which is how a ``cancel_requested`` raised by the web process reaches this one
        without a query of its own — within one flush interval. Also refreshes
        ``updated_at``, which doubles as a liveness marker.

        :param task: The task document to update in place.
        :type task: TTask
        :param current: Work done so far, in the task's own progress unit.
        :type current: int
        :rtype: None
        """
        task_id = str(task.id)
        now = time()
        if now - self._last_flush_at.get(task_id, 0.0) < self._progress_flush_interval:
            return
        self._last_flush_at[task_id] = now

        before = self._dump(task)
        task.set_progress(current)
        task.updated_at = now
        await task.set(self._changed_fields(before, task))
        if task.cancel_requested:
            self._cancel_requested[task_id] = True

    @staticmethod
    def _dump(task: TTask) -> dict[str, Any]:
        return task.model_dump(by_alias=True)

    @classmethod
    def _changed_fields(cls, before: dict[str, Any], task: TTask) -> dict[str, Any]:
        """
        The stored fields that differ between an earlier dump and the task now.

        Lets the template persist what a subclass hook changed — ``set_progress`` or a
        compensation — without knowing which fields that subclass keeps its progress in.

        :param before: A ``_dump`` of the task taken before the change.
        :type before: dict[str, Any]
        :param task: The task after the change.
        :type task: TTask
        :return: Field name to new value, for every field whose value changed.
        :rtype: dict[str, Any]
        """
        after = cls._dump(task)
        return {key: value for key, value in after.items() if before.get(key) != value}

    def _make_progress(
        self,
        task: TTask,
        current: int | None = None,
        message: str | None = None,
    ) -> ProgressFrame:
        """
        Build a progress frame from a task's current state.

        Reads through the model's progress accessors rather than any particular field, so
        the template works for tasks that measure something other than bytes.

        :param task: The task to describe.
        :type task: TTask
        :param current: Live progress count. Falls back to the persisted value when
            omitted, which is what phases outside the main work loop rely on.
        :type current: int | None
        :param message: Optional note to attach to the frame.
        :type message: str | None
        :return: The assembled frame; percentage is derived by the frame itself.
        :rtype: ProgressFrame
        """
        stored_current, total = task.get_progress()
        return ProgressFrame(
            task_id=str(task.id),
            status=task.status,
            current=stored_current if current is None else current,
            total=total,
            message=message,
        )
