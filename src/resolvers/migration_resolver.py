from typing import AsyncGenerator

import strawberry

from src.context import ContextEnum, get_context_value
from src.errors import InputValidationError
from src.logger import get_logger
from src.schema.types.migration_type import (
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
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.features.catalog.catalog_service import CatalogService
from src.features.migration.migration_service import MigrationService
from src.platform.jobs.dispatch import TaskDispatcher
from src.platform.jobs.progress_bus import ProgressBus, ProgressPublisher
from src.platform.jobs.task_model import TaskStatus
from src.platform.storage.absolute_path import AbsolutePath

logger = get_logger("migration_resolver")


async def _resolve_source_path(video_id: str, info: strawberry.Info) -> AbsolutePath:
    """
    Look up a video by ID and wrap its stored path as an AbsolutePath.

    The migration API takes a video ID rather than a path, so the caller cannot point a
    migration at an arbitrary location — the source always comes from an existing record.

    :param video_id: The video's ObjectId, as a string.
    :type video_id: str
    :param info: Strawberry GraphQL info object, used to reach the resource handler service.
    :type info: strawberry.Info
    :return: The video's path, bound to the handler for its category.
    :rtype: AbsolutePath
    :raises InputValidationError: If the ID is malformed or matches no video.
    """
    catalog_service: CatalogService = get_context_value(info, ContextEnum.CATALOG_SERVICE)
    try:
        video = await catalog_service.get_video(video_id)
    except Exception:
        raise InputValidationError(field="sourceVideoId", issue="Video not found")

    handler_service: ResourceHandlerService = get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE)
    handler = handler_service.get_handler(video.category)
    return AbsolutePath.from_existing_path(video.path, category=video.category, handler=handler)


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
    try:
        validated = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="MigrationPreflightInput", issue="Invalid input data")

    handler_service = get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE)
    settings = get_context_value(info, ContextEnum.SETTINGS)

    source_path = await _resolve_source_path(validated.source_video_id, info)
    target_dir_path = AbsolutePath.from_relative_path(
        parsedPath=validated.target_dir_relative_path.parsedPath,
        handlerService=handler_service,
        settings=settings,
    )

    service: MigrationService = get_context_value(info, ContextEnum.MIGRATION_SERVICE)
    result = await service.preflight(source_path, target_dir_path)

    return MigrationPreflightResult(
        valid=result.valid,
        source_file_size=result.source_file_size,
        conflict_exists=result.conflict_exists,
        space_available=result.space_available,
        space_sufficient=result.space_sufficient,
        already_migrating=result.already_migrating,
        same_location=result.same_location,
        error_message=result.error_message,
    )


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
    try:
        validated = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="CreateMigrationTaskInput", issue="Invalid input data")

    handler_service = get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE)
    settings = get_context_value(info, ContextEnum.SETTINGS)

    source_path = await _resolve_source_path(validated.source_video_id, info)
    target_dir_path = AbsolutePath.from_relative_path(
        parsedPath=validated.target_dir_relative_path.parsedPath,
        handlerService=handler_service,
        settings=settings,
    )

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
    try:
        validated = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="MigrationTaskActionInput", issue="Invalid input data")

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
    try:
        validated = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="MigrationTaskActionInput", issue="Invalid input data")

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
    try:
        validated = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="MigrationTaskActionInput", issue="Invalid input data")

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
    try:
        validated = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="MigrationTaskQueryInput", issue="Invalid input data")

    migration_service: MigrationService = get_context_value(info, ContextEnum.MIGRATION_SERVICE)
    task_models, total_count = await migration_service.list_tasks(
        status_filter=validated.status_filter,
        page=validated.page,
        page_size=validated.page_size,
    )

    tasks = [MigrationTask.from_model(m) for m in task_models]
    return MigrationTaskListResult(
        tasks=tasks,
        total_count=total_count,
        page=validated.page,
        page_size=validated.page_size,
    )
