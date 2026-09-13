"""Unit tests for TaskRunner — queueing, concurrency, observation and recovery."""

import asyncio

import pytest

from src.platform.jobs.progress import ProgressFrame
from src.platform.jobs.task_model import TaskStatus
from src.platform.jobs.task_runner import TaskRunner

pytestmark = pytest.mark.unit

EXECUTOR_KEY = "demo"


def _frame(task_id: str, status=TaskStatus.PROCESSING, current=0) -> ProgressFrame:
    return ProgressFrame(
        task_id=task_id,
        status=status,
        current=current,
        total=100,
        message=None,
    )


class FakeExecutor:
    """Stands in for a StateMachine; records what the runner asked it to do."""

    def __init__(self, frames_per_task: int = 2, hold: bool = False):
        self.frames_per_task = frames_per_task
        self.calls: list[tuple[str, TaskStatus]] = []
        self.recovery_plan: list[tuple[str, TaskStatus]] = []
        self.gate = asyncio.Event() if hold else None
        self.started = asyncio.Event()
        self.concurrent = 0
        self.peak_concurrent = 0

    async def run_task(self, task_id, start_from=TaskStatus.PROCESSING):
        self.calls.append((task_id, start_from))
        self.concurrent += 1
        self.peak_concurrent = max(self.peak_concurrent, self.concurrent)
        self.started.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            for i in range(self.frames_per_task):
                yield _frame(task_id, current=i)
                await asyncio.sleep(0)
        finally:
            self.concurrent -= 1

    async def build_snapshot(self, task_id):
        return _frame(task_id, status=TaskStatus.COMPLETED, current=100)

    async def plan_recovery(self):
        return self.recovery_plan


async def _drain_queue(runner: TaskRunner) -> None:
    await asyncio.wait_for(runner.wait_idle(), timeout=5)


@pytest.fixture
async def runner_factory():
    created: list[TaskRunner] = []

    def _make(executor, max_concurrent=2) -> TaskRunner:
        runner = TaskRunner(max_concurrent=max_concurrent)
        runner.register_executor(EXECUTOR_KEY, executor)
        runner.start()
        created.append(runner)
        return runner

    yield _make

    for runner in created:
        await runner.shutdown()


# =======================================================================
# submission
# =======================================================================

class TestSubmit:
    async def test_submitted_task_runs_without_any_observer(self, runner_factory):
        """The whole point: execution must not wait for a client to connect."""
        executor = FakeExecutor()
        runner = runner_factory(executor)

        await runner.submit("task-1", executor_key=EXECUTOR_KEY)
        await _drain_queue(runner)

        assert executor.calls == [("task-1", TaskStatus.PROCESSING)]

    async def test_start_from_is_passed_through(self, runner_factory):
        executor = FakeExecutor()
        runner = runner_factory(executor)

        await runner.submit("task-1", executor_key=EXECUTOR_KEY, start_from=TaskStatus.DELETING_SOURCE)
        await _drain_queue(runner)

        assert executor.calls == [("task-1", TaskStatus.DELETING_SOURCE)]

    async def test_duplicate_submit_is_ignored(self, runner_factory):
        """Guards against a retry and a recovery both queueing the same task."""
        executor = FakeExecutor(hold=True)
        runner = runner_factory(executor)

        await runner.submit("task-1", executor_key=EXECUTOR_KEY)
        await asyncio.wait_for(executor.started.wait(), timeout=5)
        await runner.submit("task-1", executor_key=EXECUTOR_KEY)

        executor.gate.set()
        await _drain_queue(runner)

        assert len(executor.calls) == 1

    async def test_unknown_executor_rejected(self, runner_factory):
        runner = runner_factory(FakeExecutor())
        with pytest.raises(KeyError):
            await runner.submit("task-1", executor_key="nope")

    async def test_concurrency_is_capped(self, runner_factory):
        executor = FakeExecutor(hold=True)
        runner = runner_factory(executor, max_concurrent=2)

        for i in range(5):
            await runner.submit(f"task-{i}", executor_key=EXECUTOR_KEY)
        await asyncio.wait_for(executor.started.wait(), timeout=5)
        await asyncio.sleep(0.05)

        assert executor.peak_concurrent <= 2

        executor.gate.set()
        await _drain_queue(runner)
        assert len(executor.calls) == 5

    async def test_crashing_task_does_not_kill_the_worker(self, runner_factory):
        class Boom(FakeExecutor):
            async def run_task(self, task_id, start_from=TaskStatus.PROCESSING):
                self.calls.append((task_id, start_from))
                if task_id == "bad":
                    raise RuntimeError("boom")
                yield _frame(task_id)

        executor = Boom()
        runner = runner_factory(executor, max_concurrent=1)

        await runner.submit("bad", executor_key=EXECUTOR_KEY)
        await runner.submit("good", executor_key=EXECUTOR_KEY)
        await _drain_queue(runner)

        assert ("good", TaskStatus.PROCESSING) in executor.calls


# =======================================================================
# observation
# =======================================================================

class TestObserve:
    async def test_observer_receives_frames(self, runner_factory):
        executor = FakeExecutor(frames_per_task=3, hold=True)
        runner = runner_factory(executor)

        await runner.submit("task-1", executor_key=EXECUTOR_KEY)
        await asyncio.wait_for(executor.started.wait(), timeout=5)

        async def collect():
            return [f async for f in runner.observe("task-1", executor_key=EXECUTOR_KEY)]

        collector = asyncio.create_task(collect())
        await asyncio.sleep(0)
        executor.gate.set()

        frames = await asyncio.wait_for(collector, timeout=5)
        assert len(frames) >= 3
        assert all(f.task_id == "task-1" for f in frames)

    async def test_multiple_observers_all_get_frames(self, runner_factory):
        """Several tabs watching one task must not interfere with each other."""
        executor = FakeExecutor(frames_per_task=3, hold=True)
        runner = runner_factory(executor)

        await runner.submit("task-1", executor_key=EXECUTOR_KEY)
        await asyncio.wait_for(executor.started.wait(), timeout=5)

        async def collect():
            return [f async for f in runner.observe("task-1", executor_key=EXECUTOR_KEY)]

        a = asyncio.create_task(collect())
        b = asyncio.create_task(collect())
        await asyncio.sleep(0)
        executor.gate.set()

        frames_a, frames_b = await asyncio.wait_for(asyncio.gather(a, b), timeout=5)
        assert len(frames_a) >= 3
        assert len(frames_b) >= 3
        assert executor.calls == [("task-1", TaskStatus.PROCESSING)]

    async def test_observing_never_starts_a_job(self, runner_factory):
        """Reconnecting after a refresh must not launch a second copy."""
        executor = FakeExecutor()
        runner = runner_factory(executor)

        frames = [f async for f in runner.observe("never-submitted", executor_key=EXECUTOR_KEY)]

        assert executor.calls == []
        # Falls back to the persisted snapshot, then completes.
        assert len(frames) == 1
        assert frames[0].status == TaskStatus.COMPLETED

    async def test_detaching_does_not_disturb_the_job(self, runner_factory):
        executor = FakeExecutor(frames_per_task=3, hold=True)
        runner = runner_factory(executor)

        await runner.submit("task-1", executor_key=EXECUTOR_KEY)
        await asyncio.wait_for(executor.started.wait(), timeout=5)

        # Attach, take nothing, walk away — as a closed browser tab would.
        agen = runner.observe("task-1", executor_key=EXECUTOR_KEY)
        await agen.__anext__()
        await agen.aclose()

        executor.gate.set()
        await _drain_queue(runner)

        assert len(executor.calls) == 1
        assert runner._observer_channels.get("task-1") in (None, set())

    async def test_observer_attached_after_completion_completes(self, runner_factory):
        executor = FakeExecutor()
        runner = runner_factory(executor)

        await runner.submit("task-1", executor_key=EXECUTOR_KEY)
        await _drain_queue(runner)

        frames = await asyncio.wait_for(
            asyncio.create_task(_collect_observe(runner, "task-1")), timeout=5
        )
        assert len(frames) == 1


async def _collect_observe(runner, task_id):
    return [f async for f in runner.observe(task_id, executor_key=EXECUTOR_KEY)]


# =======================================================================
# recovery
# =======================================================================

class TestRecover:
    async def test_recovered_tasks_are_requeued_with_their_resume_point(self, runner_factory):
        executor = FakeExecutor()
        executor.recovery_plan = [
            ("orphan-1", TaskStatus.PROCESSING),
            ("orphan-2", TaskStatus.DELETING_SOURCE),
        ]
        runner = runner_factory(executor)

        await runner.recover()
        await _drain_queue(runner)

        assert set(executor.calls) == {
            ("orphan-1", TaskStatus.PROCESSING),
            ("orphan-2", TaskStatus.DELETING_SOURCE),
        }

    async def test_recovery_failure_does_not_break_startup(self, runner_factory):
        class Broken(FakeExecutor):
            async def plan_recovery(self):
                raise RuntimeError("db down")

        runner = runner_factory(Broken())
        await runner.recover()  # must not raise
