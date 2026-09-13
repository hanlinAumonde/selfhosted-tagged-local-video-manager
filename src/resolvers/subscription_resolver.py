from typing import AsyncGenerator
from fastapi.concurrency import run_in_threadpool
import strawberry
from src.context import ContextEnum, get_context_value
from src.errors import InputValidationError
from src.logger import get_logger
from src.schema.types.fileBrowse_type import (
    BatchOperationStatus,
    VideosBatchOperationInput
)
from src.features.browsing.batch_operation_service import BatchOperationService
from src.features.browsing.directory_deletion import DirectoryDeletionStrategy
from src.features.catalog.catalog_service import CatalogService
from src.features.browsing.browse_file_service import BrowseFileService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.resource_handler_service import ResourceHandlerService

logger = get_logger("SubscriptionResolver")

async def resolve_batch_operations(input: VideosBatchOperationInput,
                                   update: bool,
                                   info: strawberry.Info) -> AsyncGenerator[BatchOperationStatus, None]:
    """
    Resolve function to batch update or delete videos based on provided video IDs or directory path.

    :param input: Input containing video IDs or relative path for batch operation.
    :type input: VideosBatchOperationInput
    :return: An asynchronous generator yielding the status of the batch update operation.
    :rtype: AsyncGenerator[BatchOperationStatus, None]
    """
    try:
        validated_input = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="VideosBatchOperationInput", issue="Invalid input data for batch updating videos")

    dir_path = AbsolutePath.from_relative_path(
        parsedPath=validated_input.relativePath.parsedPath,
        handlerService=get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE),
        settings=get_context_value(info, ContextEnum.SETTINGS)
    )
    category = dir_path.category

    series_operation = validated_input.seriesOperation
    by_ids = validated_input.videoIds is not None and len(validated_input.videoIds) > 0

    directory_deletion = _resolve_directory_deletion(
        validated_input.directoryDeletion, update=update, by_ids=by_ids, dir_path=dir_path
    )

    if series_operation is not None:
        if not update:
            raise InputValidationError(field="seriesOperation", issue="Series operation is only allowed in batch update, not delete")
        if not by_ids:
            raise InputValidationError(field="seriesOperation", issue="Series operation requires an explicit videoIds list")
        if not series_operation.clear:
            if not series_operation.name:
                raise InputValidationError(field="seriesOperation", issue="Series name is required when clear is false")
            orders_ids = {entry.videoId for entry in series_operation.orders}
            selected_ids = set(validated_input.videoIds)
            if orders_ids != selected_ids:
                raise InputValidationError(field="seriesOperation", issue="Series orders must cover exactly the selected video IDs")
    
    batchOperationService: BatchOperationService = get_context_value(info, ContextEnum.BATCH_OPERATION_SERVICE)
    if by_ids:
        catalogService: CatalogService = get_context_value(info, ContextEnum.CATALOG_SERVICE)
        await catalogService.assert_videos_unlocked(validated_input.videoIds)

        if update:
            async for status in batchOperationService.batch_update(
                category=category,
                videoIDs=validated_input.videoIds,
                fileEntries=None,
                author=validated_input.author,
                tagsOperation=validated_input.tagsOperation,
                seriesOperation=series_operation,
            ):
                yield BatchOperationStatus.from_service(status)
        else:
            async for status in batchOperationService.batch_delete(
                dir_path=dir_path,
                videoIds=validated_input.videoIds,
                fileEntries=None
            ):
                yield BatchOperationStatus.from_service(status)
        return

    # By directory path — expand virtual paths to real mounted paths, collect all entries
    category_path_pairs = _expand_directory_path(dir_path, info)
    all_entries = []
    for cat, abs_path in category_path_pairs:
        browseFileService: BrowseFileService = get_context_value(info, ContextEnum.BROWSE_FILE_SERVICE)
        entries = await run_in_threadpool(
            browseFileService.get_all_video_entries_in_directory,
            abs_path.FS_format_path(),
            cat
        )
        if entries:
            all_entries.extend(entries)
            yield BatchOperationStatus.from_service(batchOperationService.constructBatchOperationStatus(
                status=f"Scanning '{abs_path.get_path()}' — {len(all_entries)} videos found so far"
            ))

    yield BatchOperationStatus.from_service(batchOperationService.constructBatchOperationStatus(
        status=f"Found {len(all_entries)} video entries in '{validated_input.relativePath.relativePath}'"
    ))

    if update:
        async for status in batchOperationService.batch_update(
            category=category,
            videoIDs=None,
            fileEntries=all_entries,
            author=validated_input.author,
            tagsOperation=validated_input.tagsOperation,
        ):
            yield BatchOperationStatus.from_service(status)
    else:
        async for status in batchOperationService.batch_delete(
            dir_path=dir_path,
            videoIds=None,
            fileEntries=all_entries,
            directoryDeletion=directory_deletion,
        ):
            yield BatchOperationStatus.from_service(status)


def _resolve_directory_deletion(requested: DirectoryDeletionStrategy | None,
                                update: bool,
                                by_ids: bool,
                                dir_path: AbsolutePath) -> DirectoryDeletionStrategy | None:
    """
    Decide what the request is asking of the directory itself.

    Deleting by directory is always a "Delete all" on a folder, so it always gets an
    answer; a client that names none means the folder stays, which is what the menu item
    did before the choice existed. Everything else must not carry one at all — an update
    never removes a folder, and a request that names videos is not about a folder.

    :param requested: The strategy the client sent, if any.
    :type requested: DirectoryDeletionStrategy | None
    :param update: Whether this is a batch update rather than a batch delete.
    :type update: bool
    :param by_ids: Whether the request names videos rather than a directory.
    :type by_ids: bool
    :param dir_path: The path the request is about.
    :type dir_path: AbsolutePath
    :return: The strategy to hand the service, or None when the folder is not in play.
    :rtype: DirectoryDeletionStrategy | None
    :raises InputValidationError: If a strategy was sent where it means nothing.
    """
    if update or by_ids:
        if requested is not None:
            raise InputValidationError(
                field="directoryDeletion",
                issue="a deletion strategy only applies when deleting by directory",
            )
        return None

    if dir_path.is_root_level() or dir_path.is_category_level():
        if requested is not None:
            raise InputValidationError(
                field="directoryDeletion",
                issue="only a directory on the storage can be deleted",
            )
        return None

    return requested or DirectoryDeletionStrategy.KeepFolder


def _expand_directory_path(dir_path: AbsolutePath, info: strawberry.Info) -> list[tuple[str, AbsolutePath]]:
    """
    Expand a virtual directory path (root/category level) into real mounted paths.

    :param dir_path: The virtual directory path to expand
    :type dir_path: AbsolutePath
    :return: A list of tuples containing the category and the corresponding absolute path
    :rtype: list[tuple[str, AbsolutePath]]
    """
    resourceHandlerService: ResourceHandlerService = get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE)
    settings = get_context_value(info, ContextEnum.SETTINGS)
    if dir_path.is_root_level():
        return [
            (cat, AbsolutePath.from_relative_path(
                    parsedPath=(cat, pn, None),
                    handlerService=resourceHandlerService,
                    settings=settings
            ))
            for cat in resourceHandlerService.get_all_categories()
            for pn in resourceHandlerService.get_pseudo_names(cat)
        ]
    elif dir_path.is_category_level():
        category = dir_path.category
        return [
            (category, AbsolutePath.from_relative_path(
                parsedPath=(category, pn, None),
                handlerService=resourceHandlerService,
                settings=settings
            ))
            for pn in resourceHandlerService.get_pseudo_names(category)
        ]
    else:
        return [(dir_path.category, dir_path)]