from typing import Optional
import pymongo
from pymongo import IndexModel

from src.platform.jobs.task_model import BaseTaskModel, TaskStatus

# TaskStatus used to be defined here. Re-exported so the many modules that import it from
# this path keep working while the task template is being generalised.
__all__ = ["MigrationTaskModel", "TaskStatus"]


class MigrationTaskModel(BaseTaskModel):
    # Path info (DB format)
    source_path: str
    source_category: str
    target_path: str
    target_category: str
    file_name: str

    # File info
    file_size: int
    bytes_transferred: int = 0

    # Conflict resolution
    conflict_strategy: Optional[str] = None
    renamed_target_path: Optional[str] = None

    # The file stays at the source until the database phase renames it. Stored because a
    # replay of that phase in a new process cannot tell this from the state the world is in.
    move_by_rename: bool = False

    def get_progress(self) -> tuple[int, int]:
        """
        Progress in bytes copied out of the file's total size.

        :return: Bytes transferred so far and the source file's size.
        :rtype: tuple[int, int]
        """
        return self.bytes_transferred, self.file_size

    def set_progress(self, current: int) -> None:
        """
        Record bytes copied so far.

        :param current: Bytes transferred.
        :type current: int
        :rtype: None
        """
        self.bytes_transferred = current

    class Settings:
        name = "migration_tasks"
        indexes = [
            [("status", pymongo.ASCENDING)],
            [("created_at", pymongo.DESCENDING)],
            [("source_path", pymongo.ASCENDING)],
            [("target_path", pymongo.ASCENDING)],
            IndexModel(
                [("source_path", pymongo.ASCENDING)],
                unique=True,
                partialFilterExpression={
                    "status": {"$in": [
                        "PENDING", "PROCESSING", "PROCESS_DONE",
                        "UPDATING_DB", "DB_UPDATED", "DELETING_SOURCE",
                    ]}
                },
            ),
            IndexModel(
                [("target_path", pymongo.ASCENDING)],
                unique=True,
                partialFilterExpression={
                    "status": {"$in": [
                        "PENDING", "PROCESSING", "PROCESS_DONE",
                        "UPDATING_DB", "DB_UPDATED", "DELETING_SOURCE",
                    ]}
                },
            ),
        ]
