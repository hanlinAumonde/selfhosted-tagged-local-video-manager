from abc import abstractmethod
from enum import Enum
from typing import Optional

from beanie import Document


class TaskStatus(str, Enum):
    """
    Lifecycle of a background task driven through the three-phase template.

    The phase statuses are named after the migration flow that introduced them, and the
    values are persisted, so they are kept as-is: renaming a value would mean rewriting
    stored documents and the frontend's status mapping. Read them structurally —
    PROCESSING is "move the payload", UPDATING_DB is "update records", DELETING_SOURCE is
    "settle the filesystem".
    """

    # Normal flow
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESS_DONE = "PROCESS_DONE"
    UPDATING_DB = "UPDATING_DB"
    DB_UPDATED = "DB_UPDATED"
    DELETING_SOURCE = "DELETING_SOURCE"
    COMPLETED = "COMPLETED"

    # Abnormal / interrupted
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BaseTaskModel(Document):
    """
    Fields every background task carries, regardless of what it actually does.

    A template only: it is never handed to ``init_beanie`` and therefore owns no
    collection. Each concrete task type subclasses it, adds its own fields, and declares
    its own ``Settings.name``.

    Progress is exposed through accessors rather than stored fields so that subclasses can
    map them onto whatever unit they already persist — bytes for a file copy, frames for a
    transcode — without this class dictating a schema they would have to migrate to.
    """

    status: str = TaskStatus.PENDING
    error_message: Optional[str] = None

    # Phase the task broke in, which is what lets a retry resume rather than restart.
    failed_step: Optional[str] = None

    created_at: float
    updated_at: float
    completed_at: Optional[float] = None

    # Phase a PENDING task starts at when it is claimed. Stored rather than carried in the
    # queue message so a redelivered message, a recovery and a retry all agree on it.
    resume_from: Optional[str] = None

    # Set by the web process; the worker reads it back on its next progress flush.
    cancel_requested: bool = False

    # Last time the task id was put on its queue; reconciliation re-sends stale ones.
    dispatched_at: Optional[float] = None

    @abstractmethod
    def get_progress(self) -> tuple[int, int]:
        """
        Report progress as a ``(current, total)`` pair in the task's own unit.

        A task with no meaningful progress should return ``(0, 0)``; the template treats a
        zero total as "not measurable" and reports 0%.

        :return: Work done so far and the total expected.
        :rtype: tuple[int, int]
        """
        ...

    @abstractmethod
    def set_progress(self, current: int) -> None:
        """
        Record progress in the task's own unit, in memory only.

        Persisting is the state machine's call — it throttles writes rather than saving on
        every frame.

        :param current: Work done so far, in the same unit ``get_progress`` reports.
        :type current: int
        :rtype: None
        """
        ...
