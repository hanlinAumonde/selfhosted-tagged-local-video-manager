from enum import Enum
from typing import Optional

import strawberry

from src.features.migration import migration_service
from src.features.migration.migration_batch import BatchSummary
from src.features.migration.migration_task_model import MigrationTaskModel
from src.platform.jobs.progress import ProgressFrame
from src.schema.types.fileBrowse_type import RelativePathInput
from src.schema.types.scalars import BigInt
from src.schema.types.pydantic_types.migration_type import (
    CreateMigrationBatchInputModel,
    MigrationBatchActionInputModel,
    MigrationBatchPreflightInputModel,
    MigrationPreflightInputModel,
    CreateMigrationTaskInputModel,
    MigrationTaskActionInputModel,
    MigrationTaskQueryInputModel,
)


@strawberry.enum
class MigrationStatusEnum(Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESS_DONE = "PROCESS_DONE"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    CLEANING_UP = "CLEANING_UP"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@strawberry.type
class MigrationPreflightResult:
    valid: bool
    source_file_size: BigInt
    conflict_exists: bool
    space_available: BigInt | None
    space_sufficient: bool | None
    already_migrating: bool
    same_location: bool
    error_message: str | None = None

    @classmethod
    def from_service(
        cls, result: migration_service.MigrationPreflightResult
    ) -> "MigrationPreflightResult":
        """
        Publish a single-file preflight result.

        :param result: The service's preflight result.
        :type result: migration_service.MigrationPreflightResult
        :rtype: MigrationPreflightResult
        """
        return cls(
            valid=result.valid,
            source_file_size=result.source_file_size,
            conflict_exists=result.conflict_exists,
            space_available=result.space_available,
            space_sufficient=result.space_sufficient,
            already_migrating=result.already_migrating,
            same_location=result.same_location,
            error_message=result.error_message,
        )


@strawberry.type
class MigrationTask:
    id: strawberry.ID
    source_path: str
    source_category: str
    target_path: str
    target_category: str
    file_name: str
    file_size: BigInt
    bytes_transferred: BigInt
    status: MigrationStatusEnum
    error_message: str | None
    failed_step: str | None
    conflict_strategy: str | None
    renamed_target_path: str | None
    created_at: float
    updated_at: float
    completed_at: float | None
    batch_id: strawberry.ID | None

    @classmethod
    def from_model(cls, model: MigrationTaskModel) -> "MigrationTask":
        """
        Publish a stored migration task.

        :param model: The task document.
        :type model: MigrationTaskModel
        :rtype: MigrationTask
        """
        return cls(
            id=strawberry.ID(str(model.id)),
            source_path=model.source_path,
            source_category=model.source_category,
            target_path=model.target_path,
            target_category=model.target_category,
            file_name=model.file_name,
            file_size=model.file_size,
            bytes_transferred=model.bytes_transferred,
            status=MigrationStatusEnum(model.status),
            error_message=model.error_message,
            failed_step=model.failed_step,
            conflict_strategy=model.conflict_strategy,
            renamed_target_path=model.renamed_target_path,
            created_at=model.created_at,
            updated_at=model.updated_at,
            completed_at=model.completed_at,
            batch_id=strawberry.ID(str(model.batch_id)) if model.batch_id else None,
        )


@strawberry.type
class MigrationTaskListResult:
    tasks: list[MigrationTask]
    total_count: int
    page: int
    page_size: int


@strawberry.type
class MigrationProgressStatus:
    task_id: str
    status: MigrationStatusEnum
    bytes_transferred: BigInt
    total_bytes: BigInt
    progress_percentage: float
    message: str | None = None

    @classmethod
    def from_service(cls, frame: ProgressFrame) -> "MigrationProgressStatus":
        """
        Republish a generic progress frame under the byte-named fields the frontend
        queries.

        The task template counts progress in unit-agnostic ``current``/``total``; migration
        measures bytes, and this schema has been published as ``bytesTransferred`` /
        ``totalBytes`` since before the template was generalised. Renaming the GraphQL
        fields would force a frontend change for no gain, so the mapping lives here.

        :param frame: Progress frame emitted by the task's state machine.
        :type frame: ProgressFrame
        :return: The frame in its published shape.
        :rtype: MigrationProgressStatus
        """
        return cls(
            task_id=frame.task_id,
            status=MigrationStatusEnum(frame.status),
            bytes_transferred=frame.current,
            total_bytes=frame.total,
            progress_percentage=frame.percentage,
            message=frame.message,
        )


@strawberry.type
class MigrationTaskMutationResult:
    success: bool
    task: Optional[MigrationTask] = None
    error_message: str | None = None


@strawberry.type
class MigrationBatchPreflightItem:
    source_video_id: strawberry.ID
    result: MigrationPreflightResult


@strawberry.type
class MigrationBatchPreflightResult:
    valid: bool
    total_size: BigInt
    space_available: BigInt | None
    space_sufficient: bool | None
    items: list[MigrationBatchPreflightItem]


@strawberry.type
class SkippedMigrationSource:
    source_video_id: strawberry.ID
    reason: str


@strawberry.type
class CreateMigrationBatchResult:
    batch_id: strawberry.ID | None
    tasks: list[MigrationTask]
    skipped: list[SkippedMigrationSource]


@strawberry.type
class MigrationBatchSummary:
    batch_id: strawberry.ID
    total: int
    active: int
    completed: int
    failed: int
    cancelled: int

    @classmethod
    def from_service(cls, summary: BatchSummary) -> "MigrationBatchSummary":
        """
        Publish a batch summary.

        :param summary: The service's count of the batch's children by state.
        :type summary: BatchSummary
        :rtype: MigrationBatchSummary
        """
        return cls(
            batch_id=strawberry.ID(summary.batch_id),
            total=summary.total,
            active=summary.active,
            completed=summary.completed,
            failed=summary.failed,
            cancelled=summary.cancelled,
        )


@strawberry.type
class MigrationBatchProgress:
    """The batch's counts when they may have changed, and a child's frame when one came."""

    summary: MigrationBatchSummary | None = None
    task: MigrationProgressStatus | None = None


# --- Input types ---

@strawberry.experimental.pydantic.input(model=MigrationPreflightInputModel)
class MigrationPreflightInput:
    source_video_id: strawberry.auto
    target_dir_relative_path: RelativePathInput


@strawberry.experimental.pydantic.input(model=CreateMigrationTaskInputModel)
class CreateMigrationTaskInput:
    source_video_id: strawberry.auto
    target_dir_relative_path: RelativePathInput
    conflict_strategy: strawberry.auto


@strawberry.experimental.pydantic.input(model=MigrationTaskActionInputModel)
class MigrationTaskActionInput:
    task_id: strawberry.auto


@strawberry.experimental.pydantic.input(model=MigrationTaskQueryInputModel)
class MigrationTaskQueryInput:
    status_filter: strawberry.auto
    page: strawberry.auto
    page_size: strawberry.auto
    batch_id: strawberry.auto


@strawberry.experimental.pydantic.input(model=MigrationBatchPreflightInputModel)
class MigrationBatchPreflightInput:
    source_video_ids: strawberry.auto
    target_dir_relative_path: RelativePathInput


@strawberry.experimental.pydantic.input(model=CreateMigrationBatchInputModel)
class CreateMigrationBatchInput:
    source_video_ids: strawberry.auto
    target_dir_relative_path: RelativePathInput
    conflict_strategy: strawberry.auto


@strawberry.experimental.pydantic.input(model=MigrationBatchActionInputModel)
class MigrationBatchActionInput:
    batch_id: strawberry.auto
