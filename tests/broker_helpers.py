from taskiq import InMemoryBroker

from src.platform.jobs.dispatch import RUN_TASK


class RecordingBroker(InMemoryBroker):
    """A real taskiq broker whose worker side just writes down the ids it receives."""

    def __init__(self):
        super().__init__(await_inplace=True)
        self.delivered: list[str] = []

        async def run_task(task_id: str) -> None:
            self.delivered.append(task_id)

        self.register_task(run_task, task_name=RUN_TASK)
