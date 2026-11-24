from typing import AsyncGenerator
import strawberry

from src.context import ContextEnum, get_context_value
from src.logger import get_logger
from src.resolvers.utils import resolve_source_path, summary_of, target_dir_of, validate_input
from src.schema.types.migration_type import (
    CreateMigrationBatchInput,
    CreateMigrationBatchResult,
    MigrationBatchActionInput,
    MigrationBatchPreflightInput,
    MigrationBatchPreflightItem,
    MigrationBatchPreflightResult,
    MigrationBatchProgress,
    MigrationBatchSummary,
    SkippedMigrationSource,
    CreateMigrationTaskInput,
    MigrationPreflightInput,
    MigrationPreflightResult,
    MigrationProgressStatus,
    MigrationTask,
    MigrationTaskActionInput,
    MigrationTaskListResult,
    MigrationTaskMutationResult,
    MigrationTaskQueryInput,
)
from src.features.migration.migration_batch import BatchSummary, MigrationBatchService
from src.features.migration.migration_service import MigrationService
from src.workers.dispatch import TaskDispatcher
from src.platform.jobs.progress_bus import ProgressBus, ProgressPublisher
from src.platform.jobs.task_model import TaskStatus

logger = get_logger("migration_resolver")

async def resolve_migration_preflight(
    input: MigrationPreflightInput, info: strawberry.Info
) -> MigrationPreflightResult:
    """
    Resolve function to check whether a video could be migrated into a target directory.

    :param input: Input containing the source video ID and the target directory path.
    :type input: MigrationPreflightInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: The preflight findings, including whether a conflict strategy will be needed.
    :rtype: MigrationPreflightResult
    :raises InputValidationError: If the input fails validation or the source video is
        missing.
    """
    validated = validate_input(input, logger, "MigrationPreflightInput")

    source_path = await resolve_source_path(validated.source_video_id, info)
    target_dir_path = target_dir_of(validated, info)

    service: MigrationService = get_context_value(info, ContextEnum.MIGRATION_SERVICE)
    result = await service.preflight(source_path, target_dir_path)
    return MigrationPreflightResult.from_service(result)


async def resolve_create_migration_task(
    input: CreateMigrationTaskInput, info: strawberry.Info
) -> MigrationTaskMutationResult:
    """
    Resolve function to create a migration task and start it in the background.

    :param input: Input containing the source video ID, target directory and conflict
        strategy.
    :type input: CreateMigrationTaskInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: Success flag and the newly created task, in PENDING status.
    :rtype: MigrationTaskMutationResult
    :raises InputValidationError: If the input fails validation, the source video is
        missing, or the file already has an active migration task.
    """
    validated = validate_input(input, logger, "CreateMigrationTaskInput")

    source_path = await resolve_source_path(validated.source_video_id, info)
    target_dir_path = target_dir_of(validated, info)

    service: MigrationService = get_context_value(info, ContextEnum.MIGRATION_SERVICE)
    task = await service.create_task(source_path, target_dir_path, validated.conflict_strategy)

    dispatcher: TaskDispatcher = get_context_value(info, ContextEnum.MIGRATION_DISPATCHER)
    await dispatcher.submit(str(task.id))

    return MigrationTaskMutationResult(
        success=True,
        task=MigrationTask.from_model(task),
    )


async def resolve_cancel_migration_task(
    input: MigrationTaskActionInput, info: strawberry.Info
) -> MigrationTaskMutationResult:
    """
    Resolve function to cancel a migration task.

    :param input: Input containing the task ID.
    :type input: MigrationTaskActionInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: Success flag and the task as it stands right after the request.
    :rtype: MigrationTaskMutationResult
    :raises InputValidationError: If the input fails validation, the task does not exist,
        or it has already settled.
    """
    validated = validate_input(input, logger, "MigrationTaskActionInput")

    service: MigrationService = get_context_value(info, ContextEnum.MIGRATION_SERVICE)
    task = await service.cancel_task(validated.task_id)

    # A queued task is settled right here and no worker will ever run it, so nobody else
    # would send its final frame; observers would wait for their watchdog. A running task
    # is still PROCESSING here, and the worker announces its end once it stops.
    if task.status == TaskStatus.CANCELLED:
        publisher: ProgressPublisher = get_context_value(info, ContextEnum.PROGRESS_PUBLISHER)
        frame = await service.build_snapshot(validated.task_id)
        if frame is not None:
            await publisher.publish(frame)

    return MigrationTaskMutationResult(
        success=True,
        task=MigrationTask.from_model(task),
    )


async def resolve_migration_progress(
    input: MigrationTaskActionInput, info: strawberry.Info
) -> AsyncGenerator[MigrationProgressStatus, None]:
    """
    Resolve function to stream a migration task's progress over WebSocket.

    The stream opens with the task's current state, follows live updates, and completes
    once the task settles. Subscribing to a task that has already finished simply yields
    its final state and ends.

    :param input: Input containing the task ID.
    :type input: MigrationTaskActionInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :yield: Progress frames until the task reaches a terminal status.
    :rtype: AsyncGenerator[MigrationProgressStatus, None]
    :raises InputValidationError: If the input fails validation.
    """
    validated = validate_input(input, logger, "MigrationTaskActionInput")

    service: MigrationService = get_context_value(info, ContextEnum.MIGRATION_SERVICE)
    bus: ProgressBus = get_context_value(info, ContextEnum.PROGRESS_BUS)
    async for status in bus.observe(validated.task_id, service.build_snapshot):
        yield MigrationProgressStatus.from_service(status)


async def resolve_migration_retry(
    input: MigrationTaskActionInput, info: strawberry.Info
) -> AsyncGenerator[MigrationProgressStatus, None]:
    """
    Resolve function to retry a failed migration task and stream its progress.

    :param input: Input containing the task ID.
    :type input: MigrationTaskActionInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :yield: Progress frames until the retried task reaches a terminal status.
    :rtype: AsyncGenerator[MigrationProgressStatus, None]
    :raises InputValidationError: If the input fails validation, the task does not exist,
        or it is not in FAILED status.
    """
    validated = validate_input(input, logger, "MigrationTaskActionInput")

    service: MigrationService = get_context_value(info, ContextEnum.MIGRATION_SERVICE)
    dispatcher: TaskDispatcher = get_context_value(info, ContextEnum.MIGRATION_DISPATCHER)
    bus: ProgressBus = get_context_value(info, ContextEnum.PROGRESS_BUS)

    # The resume point is stored on the task; the worker reads it when it claims the task.
    await service.prepare_retry(validated.task_id)
    await dispatcher.submit(validated.task_id)

    async for status in bus.observe(validated.task_id, service.build_snapshot):
        yield MigrationProgressStatus.from_service(status)


async def resolve_get_migration_tasks(
    input: MigrationTaskQueryInput, info: strawberry.Info
) -> MigrationTaskListResult:
    """
    Resolve function to list migration tasks, newest first.

    :param input: Input containing an optional status filter and pagination parameters.
    :type input: MigrationTaskQueryInput
    :param info: Strawberry GraphQL info object. Unused — this resolver needs no injected
        service — but kept for a uniform resolver signature.
    :type info: strawberry.Info
    :return: The matching page of tasks plus the total count for pagination.
    :rtype: MigrationTaskListResult
    :raises InputValidationError: If the input fails validation.
    """
    validated = validate_input(input, logger, "MigrationTaskQueryInput")

    migration_service: MigrationService = get_context_value(info, ContextEnum.MIGRATION_SERVICE)
    task_models, total_count = await migration_service.list_tasks(
        status_filter=validated.status_filter,
        page=validated.page,
        page_size=validated.page_size,
        batch_id=validated.batch_id,
    )

    tasks = [MigrationTask.from_model(m) for m in task_models]
    return MigrationTaskListResult(
        tasks=tasks,
        total_count=total_count,
        page=validated.page,
        page_size=validated.page_size,
    )


# ----------------------------------------------------------------------
# Batch migration
# ----------------------------------------------------------------------

async def resolve_migration_batch_preflight(
    input: MigrationBatchPreflightInput, info: strawberry.Info
) -> MigrationBatchPreflightResult:
    """
    Resolve function to check whether a set of videos could be migrated into one directory.

    :param input: The source video IDs and the target directory.
    :type input: MigrationBatchPreflightInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: Each video's findings, in the order given, plus the batch-wide space check.
    :rtype: MigrationBatchPreflightResult
    :raises InputValidationError: If the input fails validation or any video is missing.
    """
    validated = validate_input(input, logger, "MigrationBatchPreflightInput")
    sources = [await resolve_source_path(video_id, info) for video_id in validated.source_video_ids]

    batches: MigrationBatchService = get_context_value(info, ContextEnum.MIGRATION_BATCH_SERVICE)
    result = await batches.preflight(sources, target_dir_of(validated, info))

    return MigrationBatchPreflightResult(
        valid=result.valid,
        total_size=result.total_size,
        space_available=result.space_available,
        space_sufficient=result.space_sufficient,
        items=[
            MigrationBatchPreflightItem(
                source_video_id=strawberry.ID(video_id),
                result=MigrationPreflightResult.from_service(item),
            )
            for video_id, item in zip(validated.source_video_ids, result.items)
        ],
    )


async def resolve_create_migration_batch(
    input: CreateMigrationBatchInput, info: strawberry.Info
) -> CreateMigrationBatchResult:
    """
    Resolve function to create a batch migration and hand every child to the queue.

    All children are sent at once; the worker runs a few at a time and leaves the rest
    queued, so the web process does not need to track the window.

    :param input: The source video IDs, the target directory and the conflict strategy.
    :type input: CreateMigrationBatchInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: The batch id (null when nothing could be added), its tasks, and the videos
        left out with the reason.
    :rtype: CreateMigrationBatchResult
    :raises InputValidationError: If the input fails validation or any video is missing.
    """
    validated = validate_input(input, logger, "CreateMigrationBatchInput")
    sources = [await resolve_source_path(video_id, info) for video_id in validated.source_video_ids]
    video_id_by_path = {
        source.DB_format_path(): video_id
        for source, video_id in zip(sources, validated.source_video_ids)
    }

    batches: MigrationBatchService = get_context_value(info, ContextEnum.MIGRATION_BATCH_SERVICE)
    creation = await batches.create_batch(
        sources, target_dir_of(validated, info), validated.conflict_strategy
    )

    dispatcher: TaskDispatcher = get_context_value(info, ContextEnum.MIGRATION_DISPATCHER)
    for task in creation.tasks:
        await dispatcher.submit(str(task.id))

    return CreateMigrationBatchResult(
        batch_id=strawberry.ID(str(creation.batch.id)) if creation.batch else None,
        tasks=[MigrationTask.from_model(task) for task in creation.tasks],
        skipped=[
            SkippedMigrationSource(
                source_video_id=strawberry.ID(video_id_by_path[skip.source_path]),
                reason=skip.reason,
            )
            for skip in creation.skipped
        ],
    )


async def resolve_cancel_migration_batch(
    input: MigrationBatchActionInput, info: strawberry.Info
) -> MigrationBatchSummary:
    """
    Resolve function to cancel every unfinished child of a batch.

    :param input: The batch ID.
    :type input: MigrationBatchActionInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: The batch's counts right after the request. Running children still count
        as active here; they stop on the worker shortly after.
    :rtype: MigrationBatchSummary
    :raises InputValidationError: If the input fails validation or the batch does not exist.
    """
    validated = validate_input(input, logger, "MigrationBatchActionInput")
    batches: MigrationBatchService = get_context_value(info, ContextEnum.MIGRATION_BATCH_SERVICE)
    settled = await batches.cancel_batch(validated.batch_id)

    # Children settled here never reach a worker, so nobody else would send their final
    # frame; the batch's observers would wait for their watchdog.
    service: MigrationService = get_context_value(info, ContextEnum.MIGRATION_SERVICE)
    publisher: ProgressPublisher = get_context_value(info, ContextEnum.PROGRESS_PUBLISHER)
    for task_id in settled:
        frame = await service.build_snapshot(task_id)
        if frame is not None:
            await publisher.publish(frame, batch_id=validated.batch_id)

    return await summary_of(batches, validated.batch_id)


async def resolve_retry_migration_batch(
    input: MigrationBatchActionInput, info: strawberry.Info
) -> MigrationBatchSummary:
    """
    Resolve function to retry every failed child of a batch.

    :param input: The batch ID.
    :type input: MigrationBatchActionInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: The batch's counts with the retried children back in the queue.
    :rtype: MigrationBatchSummary
    :raises InputValidationError: If the input fails validation or the batch does not exist.
    """
    validated = validate_input(input, logger, "MigrationBatchActionInput")
    batches: MigrationBatchService = get_context_value(info, ContextEnum.MIGRATION_BATCH_SERVICE)
    dispatcher: TaskDispatcher = get_context_value(info, ContextEnum.MIGRATION_DISPATCHER)

    for task_id in await batches.retry_batch(validated.batch_id):
        await dispatcher.submit(task_id)

    return await summary_of(batches, validated.batch_id)


async def resolve_migration_batch_progress(
    input: MigrationBatchActionInput, info: strawberry.Info
) -> AsyncGenerator[MigrationBatchProgress, None]:
    """
    Resolve function to stream a batch's progress over WebSocket.

    A pure observer: opens with the batch's counts, relays every child's frames, and
    completes once no child is active.

    :param input: The batch ID.
    :type input: MigrationBatchActionInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :yield: Counts and child frames until the batch settles.
    :rtype: AsyncGenerator[MigrationBatchProgress, None]
    :raises InputValidationError: If the input fails validation.
    """
    validated = validate_input(input, logger, "MigrationBatchActionInput")
    batches: MigrationBatchService = get_context_value(info, ContextEnum.MIGRATION_BATCH_SERVICE)
    bus: ProgressBus = get_context_value(info, ContextEnum.PROGRESS_BUS)

    def is_settled(summary: BatchSummary) -> bool:
        return summary.settled

    async for event in bus.observe_batch(validated.batch_id, batches.summarize, is_settled):
        yield MigrationBatchProgress(
            summary=MigrationBatchSummary.from_service(event.summary) if event.summary else None,
            task=MigrationProgressStatus.from_service(event.frame) if event.frame else None,
        )
