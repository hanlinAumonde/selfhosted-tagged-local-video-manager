"""A second task type, deliberately unlike migration.

Shared by every test that exercises the task template or the dispatcher: if the platform
pieces only worked for migration's shape, a task with no files and no paths is what
would show it.
"""

import asyncio
from contextlib import asynccontextmanager

from beanie.operators import Set

from src.platform.jobs.progress import ProgressFrame
from src.platform.jobs.state_machine import TaskStateMachine
from src.platform.jobs.task_model import BaseTaskModel, TaskStatus


class ReindexTaskModel(BaseTaskModel):
    """Rebuilds a search index. Touches no filesystem and has no notion of a target path."""

    documents_total: int
    documents_done: int = 0
    index_name: str = "books"

    def get_progress(self) -> tuple[int, int]:
        return self.documents_done, self.documents_total

    def set_progress(self, current: int) -> None:
        self.documents_done = current

    class Settings:
        name = "reindex_tasks"


class ReindexStateMachine(TaskStateMachine[ReindexTaskModel]):
    """Minimal executor: records which phases ran, and can be told to blow up in one."""

    task_model = ReindexTaskModel

    def __init__(self, fail_in: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.phases_run: list[str] = []
        self.compensated: list[tuple[str, TaskStatus]] = []
        self.fail_in = fail_in

    async def _execute_processing(self, task: ReindexTaskModel):
        self.phases_run.append("processing")
        await self._update_task_status(task, TaskStatus.PROCESSING)
        # Yield control once, so two concurrent runs genuinely interleave.
        await asyncio.sleep(0)
        if self.fail_in == "processing":
            raise RuntimeError("indexer crashed")
        yield self._make_progress(task, current=task.documents_total, message="indexed")
        await self._finish_processing(task)

    async def _execute_db_update(self, task: ReindexTaskModel) -> None:
        self.phases_run.append("db")
        await self._update_task_status(task, TaskStatus.UPDATING_DB)
        if self.fail_in == "db":
            raise RuntimeError("index swap failed")
        await self._update_task_status(task, TaskStatus.DB_UPDATED)

    async def _execute_fs_cleanup(self, task: ReindexTaskModel) -> str | None:
        self.phases_run.append("fs")
        await self._update_task_status(task, TaskStatus.COMPLETED)
        return None


class CompensatingReindexStateMachine(ReindexStateMachine):
    """Overrides the recovery hook to prove the template calls it."""

    async def _compensate_before_resume(
        self, task: ReindexTaskModel, start_from: TaskStatus
    ) -> None:
        self.compensated.append((str(task.id), start_from))


class RecordingSlotReindexStateMachine(ReindexStateMachine):
    """Records when its processing slot is entered and left, interleaved with the phases.

    ``gate`` lets a test hold the slot closed, to act while a task waits for it.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.events: list[str] = []
        self.status_when_slot_entered: str | None = None
        self.gate = asyncio.Event()
        self.gate.set()
        self.waiting = asyncio.Event()

    @asynccontextmanager
    async def _processing_slot(self, task: ReindexTaskModel):
        self.waiting.set()
        await self.gate.wait()
        stored = await ReindexTaskModel.get(task.id)
        self.status_when_slot_entered = stored.status
        self.events.append("slot entered")
        try:
            yield
        finally:
            self.events.append("slot left")

    async def _execute_processing(self, task):
        self.events.append("processing")
        async for frame in super()._execute_processing(task):
            yield frame

    async def _execute_db_update(self, task) -> None:
        self.events.append("db")
        await super()._execute_db_update(task)

    async def _execute_fs_cleanup(self, task) -> str | None:
        self.events.append("fs")
        return await super()._execute_fs_cleanup(task)


class UntilCancelledReindexStateMachine(ReindexStateMachine):
    """Processing keeps reporting progress until the cancel flag reaches it."""

    async def _execute_processing(self, task: ReindexTaskModel):
        self.phases_run.append("processing")
        done = 0
        while not self._cancel_requested.get(str(task.id)):
            await asyncio.sleep(0.02)
            done += 1
            await self._maybe_flush_progress(task, done)
            yield self._make_progress(task, current=done)
        await self._update_task_status(task, TaskStatus.CANCELLED)
        yield self._make_progress(task, message="cancelled")


class LateCancelReindexStateMachine(ReindexStateMachine):
    """Processing ends through ``_finish_processing``.

    With ``cancel_late`` set, another process raises the cancel flag after the phase has
    taken its last look at it — the moment a long copy reads its final chunk.
    """

    def __init__(self, cancel_late: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.cancel_late = cancel_late
        self.finished: bool | None = None

    async def _execute_processing(self, task: ReindexTaskModel):
        self.phases_run.append("processing")
        await self._update_task_status(task, TaskStatus.PROCESSING)
        yield self._make_progress(task, current=task.documents_total)
        if self.cancel_late:
            await set_stored_fields(task, cancel_requested=True)
        self.finished = await self._finish_processing(task, documents_done=task.documents_total)
        if not self.finished:
            await self._update_task_status(task, TaskStatus.CANCELLED)
            yield self._make_progress(task, message="cancelled")


async def set_stored_fields(task: ReindexTaskModel, **fields) -> None:
    """Write fields straight to the collection, as another process would."""
    # A query update rather than task.set(): the caller's copy must stay stale, as the
    # worker's copy would be.
    await ReindexTaskModel.find_one(ReindexTaskModel.id == task.id).update(Set(fields))


async def drain(machine: TaskStateMachine, task_id: str) -> list[ProgressFrame]:
    return [frame async for frame in machine.run_task(task_id)]
