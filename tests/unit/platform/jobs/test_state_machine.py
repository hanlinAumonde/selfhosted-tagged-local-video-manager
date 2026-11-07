"""
Proof that the three-phase task template is genuinely reusable.

The test drives a task type that shares nothing with migration — no source and target
paths, no files, no storage handlers — end to end through the template. If that works
without the template knowing anything about it, the abstraction is real; if the template
still needs migration's shape, these tests are what will say so.
"""

import asyncio
import inspect

import pytest

from src.platform.jobs import state_machine as state_machine_module
from src.platform.jobs.state_machine import TaskStateMachine
from src.platform.jobs.task_model import TaskStatus
from tests.unit.platform.jobs.reindex import (
    CompensatingReindexStateMachine,
    ReindexStateMachine,
    ReindexTaskModel,
    drain as _drain,
)

pytestmark = pytest.mark.unit


# =======================================================================
# The template is usable without migration
# =======================================================================

class TestGenericTaskType:
    async def test_a_non_migration_task_runs_all_three_phases(self, reindex_task_factory):
        machine = ReindexStateMachine()
        task = await reindex_task_factory()

        await _drain(machine, str(task.id))

        assert machine.phases_run == ["processing", "db", "fs"]
        assert (await ReindexTaskModel.get(task.id)).status == TaskStatus.COMPLETED

    async def test_template_needs_no_storage_or_metadata_collaborators(self):
        """The base constructor takes nothing migration-shaped; a task type that needs
        handlers injects them into its own subclass."""
        machine = ReindexStateMachine()

        assert machine._progress_flush_interval == 3.0

    async def test_progress_frames_carry_the_task_types_own_unit(self, reindex_task_factory):
        task = await reindex_task_factory(documents_total=10)

        frames = await _drain(ReindexStateMachine(), str(task.id))

        indexed = next(f for f in frames if f.message == "indexed")
        assert indexed.current == 10
        assert indexed.total == 10
        assert indexed.percentage == 100.0

    async def test_resume_point_skips_the_earlier_phases(self, reindex_task_factory):
        machine = ReindexStateMachine()
        task = await reindex_task_factory(resume_from=TaskStatus.DELETING_SOURCE)

        await _drain(machine, str(task.id))

        assert machine.phases_run == ["fs"]

    async def test_failure_records_the_phase_that_broke(self, reindex_task_factory):
        machine = ReindexStateMachine(fail_in="db")
        task = await reindex_task_factory()

        await _drain(machine, str(task.id))

        stored = await ReindexTaskModel.get(task.id)
        assert stored.status == TaskStatus.FAILED
        assert stored.failed_step == TaskStatus.UPDATING_DB.value
        assert stored.error_message == "index swap failed"

    async def test_shutdown_leaves_status_untouched_for_recovery(self, reindex_task_factory):
        """CancelledError means the process is going down, not that the task failed."""

        class HangingMachine(ReindexStateMachine):
            async def _execute_processing(self, task):
                await self._update_task_status(task, TaskStatus.PROCESSING)
                raise asyncio.CancelledError()
                yield  # pragma: no cover - makes this an async generator

        task = await reindex_task_factory()

        with pytest.raises(asyncio.CancelledError):
            await _drain(HangingMachine(), str(task.id))

        assert (await ReindexTaskModel.get(task.id)).status == TaskStatus.PROCESSING


# =======================================================================
# Model binding
# =======================================================================

class TestModelBinding:
    async def test_template_reads_the_subclasses_task_model(self, reindex_task_factory):
        """The template must never reach for a hardcoded document class."""
        task = await reindex_task_factory(documents_total=4, documents_done=1)

        frame = await ReindexStateMachine().build_snapshot(str(task.id))

        assert frame is not None
        assert frame.current == 1
        assert frame.total == 4

    async def test_missing_task_yields_no_frames(self, reindex_db):
        """A stale queue entry must not crash a worker."""
        frames = await _drain(ReindexStateMachine(), "507f1f77bcf86cd799439011")

        assert frames == []


# =======================================================================
# Recovery compensation hook
# =======================================================================

class TestRecoveryCompensation:
    async def test_plan_recovery_maps_status_to_resume_point(self, reindex_task_factory):
        task = await reindex_task_factory(status=TaskStatus.DB_UPDATED)

        plan = await ReindexStateMachine().plan_recovery()

        assert plan == [str(task.id)]
        stored = await ReindexTaskModel.get(task.id)
        assert stored.status == TaskStatus.PENDING
        assert stored.resume_from == TaskStatus.DELETING_SOURCE

    async def test_compensation_hook_defaults_to_doing_nothing(self, reindex_task_factory):
        """A task type with no side effects to undo needs no recovery code at all."""
        await reindex_task_factory(status=TaskStatus.PROCESSING)

        plan = await ReindexStateMachine().plan_recovery()

        assert len(plan) == 1

    async def test_compensation_hook_is_called_with_the_resume_point(self, reindex_task_factory):
        machine = CompensatingReindexStateMachine()
        task = await reindex_task_factory(status=TaskStatus.PROCESSING)

        await machine.plan_recovery()

        assert machine.compensated == [(str(task.id), TaskStatus.PROCESSING)]


# =======================================================================
# _should_run_phase
# =======================================================================

class TestShouldRunPhase:
    def test_processing_from_processing(self):
        assert TaskStateMachine._should_run_phase(TaskStatus.PROCESSING, TaskStatus.PROCESSING) is True

    def test_updating_db_from_processing(self):
        assert TaskStateMachine._should_run_phase(TaskStatus.PROCESSING, TaskStatus.UPDATING_DB) is True

    def test_deleting_source_from_processing(self):
        assert TaskStateMachine._should_run_phase(TaskStatus.PROCESSING, TaskStatus.DELETING_SOURCE) is True

    def test_processing_from_updating_db_is_skipped(self):
        assert TaskStateMachine._should_run_phase(TaskStatus.UPDATING_DB, TaskStatus.PROCESSING) is False

    def test_deleting_source_from_updating_db(self):
        assert TaskStateMachine._should_run_phase(TaskStatus.UPDATING_DB, TaskStatus.DELETING_SOURCE) is True

    def test_processing_from_deleting_source_is_skipped(self):
        assert TaskStateMachine._should_run_phase(TaskStatus.DELETING_SOURCE, TaskStatus.PROCESSING) is False

    def test_updating_db_from_deleting_source_is_skipped(self):
        assert TaskStateMachine._should_run_phase(TaskStatus.DELETING_SOURCE, TaskStatus.UPDATING_DB) is False

# =======================================================================
# The template stays free of migration
# =======================================================================

class TestTemplateHasNoMigrationKnowledge:
    def test_module_references_nothing_migration_specific(self):
        source = inspect.getsource(state_machine_module)

        for forbidden in (
            "MigrationTaskModel",
            "ResourceHandlerService",
            "DirMetadataService",
            "BaseResourceHandler",
            "source_path",
            "target_path",
            "renamed_target_path",
            "bytes_transferred",
        ):
            assert forbidden not in source, f"{forbidden} leaked into the generic template"
