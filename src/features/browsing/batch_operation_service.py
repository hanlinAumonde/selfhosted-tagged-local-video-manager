import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import AsyncGenerator
from bson import ObjectId
from fastapi.concurrency import run_in_threadpool
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError
from src.features.catalog.video import VideoModel
from src.errors import DatabaseOperationError, FileBrowseError, InputValidationError
from src.logger import get_logger
from src.schema.types.pydantic_types.batch_operation_type import (
    SeriesOperationInputModel,
    TagsOperationMappingInputModel,
)
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.features.browsing.directory_deletion import DirectoryDeletionStrategy
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.base_file_entry import BaseFileEntry
from src.platform.storage.base_resource_handler import BaseResourceHandler
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.features.catalog.tag_operation_service import TagOperationService
from src.features.playback.thumbnail_service import ThumbnailService

logger = get_logger("batch_operation_service")


class BatchResultType(str, Enum):
    """How a batch operation ended. Published as-is over GraphQL."""
    Success = "Success"
    PartialSuccess = "PartialSuccess"
    Failure = "Failure"
    AlreadyUpToDate = "AlreadyUpToDate"


@dataclass(slots=True)
class BatchProgress:
    """
    One progress report from a running batch operation.

    Carries either a running commentary (``status`` alone) or a settled outcome
    (``result_type`` plus ``message``); the transport decides how to render each.
    """
    result_type: BatchResultType | None = None
    message: str | None = None
    status: str | None = None

class BatchOperationService:

    def __init__(
        self,
        dir_metadata_service: DirMetadataService,
        tag_operation_service: TagOperationService,
        thumbnail_service: ThumbnailService,
        resource_handler_service: ResourceHandlerService,
        ffmpeg_service: FFmpegService,
    ):
        self.dirMetadataService = dir_metadata_service
        self.tagOperationService = tag_operation_service
        self.thumbnailService = thumbnail_service
        self.resourceHandlerService = resource_handler_service
        self.ffmpegService = ffmpeg_service

    def constructBatchOperationStatus(self, 
                                      resultType: BatchResultType | None = None,
                                      message: str | None = None,
                                      status: str | None = None) -> BatchProgress:
        """
        Build one progress report.

        A report with no result type or no message is a running commentary rather than an
        outcome, and is emitted with ``result_type`` left unset.

        :param resultType: The type of the batch operation result.
        :type resultType: BatchResultType | None
        :param message: The message associated with the batch operation result.
        :type message: str | None
        :param status: The status of the batch operation.
        :type status: str | None
        :return: The progress report.
        :rtype: BatchProgress
        """
        if resultType is None or message is None:
            return BatchProgress(status=status)
        return BatchProgress(result_type=resultType, message=message, status=status)

    async def batch_delete(self,
                           dir_path: AbsolutePath,
                           videoIds: list[str],
                           fileEntries: list[BaseFileEntry] | None,
                           directoryDeletion: DirectoryDeletionStrategy | None = None
                           ) -> AsyncGenerator[BatchProgress, None]:
        """
        Resolve function to batch delete videos based on provided video IDs or directory path.

        :param dir_path: The absolute path of the directory containing the videos to delete.
        :type dir_path: AbsolutePath
        :param videoIds: List of video IDs to delete.
        :type videoIds: list[str]
        :param fileEntries: List of file entries representing videos to delete (used if videoIds is not provided).
        :type fileEntries: list[BaseFileEntry] | None
        :param directoryDeletion: What becomes of ``dir_path`` itself. Set only when the
            request is a "Delete all" on that directory; ``None`` means the directory is
            merely where the deleted videos happened to live.
        :type directoryDeletion: DirectoryDeletionStrategy | None
        :return: An asynchronous generator yielding the status of the batch delete operation.
        :rtype: AsyncGenerator[BatchProgress, None]"""
        if directoryDeletion is not None and (
            dir_path.is_root_level() or dir_path.is_category_level()
        ):
            raise InputValidationError(
                field="relativePath",
                issue="only a directory on the storage can be deleted",
            )

        # An empty selection is normally nothing to do — but a folder with no videos in
        # it is exactly the one a user is most likely to be taking back.
        if (not videoIds and not fileEntries and directoryDeletion is None) \
                or dir_path.get_path() is None:
            yield self.constructBatchOperationStatus(
                resultType=BatchResultType.Failure,
                message="No video IDs or file entries provided for batch delete"
            )
            return

        category = dir_path.category

        selected_count = len(videoIds) if videoIds else len(fileEntries or [])
        deleted_count = 0

        try:
            if videoIds:
                videos = await VideoModel.find_many(
                    {"_id": {"$in": [ObjectId(str(vid)) for vid in videoIds]}}
                ).to_list()
                result = await VideoModel.get_pymongo_collection().delete_many(
                    {"_id": {"$in": [ObjectId(str(vid)) for vid in videoIds]}}
                )
                yield self.constructBatchOperationStatus(
                    status=f"Deleted {result.deleted_count} videos based on IDs"
                )
                videos_not_deleted = await VideoModel.find_many(
                    {"_id": {"$in": [ObjectId(str(vid)) for vid in videoIds]}}
                ).to_list()
                not_deleted_ids = {v.id for v in videos_not_deleted}
                actually_deleted = [v for v in videos if v.id not in not_deleted_ids]
                await self._remove_videos_and_update_tags(actually_deleted, category)
                deleted_count = result.deleted_count

            elif fileEntries:
                handler = self.resourceHandlerService.get_handler(category)
                paths = [handler.convert_to_DB_format_path(
                    handler.get_path_standard_format(fe.path)
                ) for fe in fileEntries]
                videos_before_delete = await VideoModel.find_many(
                    {"category": category, "path": {"$in": paths}}
                ).to_list()
                result = await VideoModel.get_pymongo_collection().delete_many(
                    {"category": category, "path": {"$in": paths}}
                )
                yield self.constructBatchOperationStatus(
                    status=f"Deleted {result.deleted_count} videos based on paths"
                )
                videos_not_deleted = await VideoModel.find_many(
                    {"category": category, "path": {"$in": paths}}
                ).to_list()
                not_deleted_paths = {v.path for v in videos_not_deleted}
                actually_deleted = [v for v in videos_before_delete if v.path not in not_deleted_paths]
                await self._remove_videos_and_update_tags(actually_deleted, category)
                deleted_count = result.deleted_count

            if directoryDeletion is None:
                await self.dirMetadataService.update_directory_metadata_forward(dir_path)
            else:
                async for progress in self._settle_directory(dir_path, directoryDeletion):
                    yield progress

            yield self._delete_outcome(selected_count, deleted_count, directoryDeletion)

        except FileBrowseError:
            raise
        except Exception as e:
            logger.exception(f"Error during batch delete: {e}")
            raise DatabaseOperationError("batch_delete", "general_failure")

    def _delete_outcome(self,
                        selected_count: int,
                        deleted_count: int,
                        directoryDeletion: DirectoryDeletionStrategy | None) -> BatchProgress:
        """
        Settle a batch delete.

        A total failure reports a message like any other outcome: a settled report with
        no message is published as running commentary, so a delete that removed nothing
        would leave the client waiting for an end that never comes.

        :param selected_count: How many videos the request named.
        :type selected_count: int
        :param deleted_count: How many of them are gone.
        :type deleted_count: int
        :param directoryDeletion: What was asked of the directory itself, if anything.
        :type directoryDeletion: DirectoryDeletionStrategy | None
        :return: The settled report.
        :rtype: BatchProgress
        """
        if selected_count == 0:
            # Only reachable for a "Delete all" on a folder that held no videos.
            return self.constructBatchOperationStatus(
                resultType=BatchResultType.Success,
                message="Deleted the folder"
                if directoryDeletion is DirectoryDeletionStrategy.DeleteFolder
                else "The folder held no videos",
            )

        if deleted_count == selected_count:
            result_type = BatchResultType.Success
        elif deleted_count > 0:
            result_type = BatchResultType.PartialSuccess
        else:
            result_type = BatchResultType.Failure

        return self.constructBatchOperationStatus(
            resultType=result_type,
            message=f"Deleted {deleted_count} out of {selected_count} videos",
        )

    async def _settle_directory(self,
                                dir_path: AbsolutePath,
                                strategy: DirectoryDeletionStrategy
                                ) -> AsyncGenerator[BatchProgress, None]:
        """
        Record what the user decided about the directory itself, once its videos are gone.

        Neither answer recurses over the storage. A sub-directory is something else that
        is inside this one, no different from a stray file: its own videos went with the
        walk, but nothing unlinks it.

        :param dir_path: The directory the "Delete all" was asked of.
        :type dir_path: AbsolutePath
        :param strategy: What the user chose for the folder.
        :type strategy: DirectoryDeletionStrategy
        :return: An asynchronous generator yielding progress for this step.
        :rtype: AsyncGenerator[BatchProgress, None]
        """
        category = dir_path.category
        handler = self.resourceHandlerService.get_handler(category)
        db_path = dir_path.DB_format_path()

        if strategy is DirectoryDeletionStrategy.KeepFolder:
            # It holds nothing now, and a directory holding nothing is hidden unless
            # something says a user wants it there. This is that something.
            await self.dirMetadataService.mark_user_created(category, db_path)
            await self.dirMetadataService.update_directory_metadata_forward(dir_path)
            yield self.constructBatchOperationStatus(status="Kept the folder")
            return

        removed = await run_in_threadpool(
            self._delete_directory_if_empty, handler, dir_path.FS_format_path()
        )
        if removed:
            await self.dirMetadataService.forget(category, db_path)
            yield self.constructBatchOperationStatus(status="Removed the folder")
        else:
            await self.dirMetadataService.mark_user_deleted(category, db_path)
            yield self.constructBatchOperationStatus(
                status="Removed the folder from the browser; it still holds other files"
            )

        parent_db_path = handler.dirname(db_path)
        if parent_db_path and parent_db_path != db_path:
            await self.dirMetadataService.update_directory_metadata_forward(
                AbsolutePath.from_existing_path(
                    path=parent_db_path, category=category, handler=handler
                )
            )

    def _delete_directory_if_empty(self, handler: BaseResourceHandler, fs_path: str) -> bool:
        """
        Take the directory off the storage, but only if nothing at all is left in it.

        A failure here is not a failed delete: the videos are already gone, and the
        directory can still be taken out of the browser by marking it.

        :param handler: The resource handler for the directory's category.
        :type handler: BaseResourceHandler
        :param fs_path: The directory's FS-format path.
        :type fs_path: str
        :return: True if the directory is no longer on the storage.
        :rtype: bool
        """
        try:
            if not handler.is_directory_empty(fs_path):
                return False
            handler.delete_directory(fs_path)
            return True
        except (OSError, Exception) as e:
            logger.exception(f"Could not remove directory {fs_path}: {e}")
            return False

    async def batch_update(self,
                           category: str,
                           videoIDs: list[str] | None,
                           fileEntries: list[BaseFileEntry] | None,
                           author: str | None,
                           tagsOperation: TagsOperationMappingInputModel,
                           seriesOperation: SeriesOperationInputModel | None = None) -> AsyncGenerator[BatchProgress, None]:
        """
        Resolve function to batch update videos based on provided video IDs or directory path, with support for updating author, tags, and series information.

        :param category: The category of the videos to update.
        :type category: str
        :param videoIDs: List of video IDs to update (if updating by IDs).
        :type videoIDs: list[str] | None
        :param fileEntries: List of file entries representing videos to update (used if updating by directory path).
        :type fileEntries: list[BaseFileEntry] | None
        :param author: The new author to set for the videos (optional).
        :type author: str | None
        :param tagsOperation: The tags operation to apply to the videos.
        :type tagsOperation: TagsOperationMappingInputModel
        :param seriesOperation: The series operation to apply to the videos (optional, only applicable when updating by IDs).
        :type seriesOperation: SeriesOperationInputModel | None
        :return: An asynchronous generator yielding the status of the batch update operation.
        :rtype: AsyncGenerator[BatchProgress, None]
        """
        if not videoIDs and not fileEntries:
            yield self.constructBatchOperationStatus(
                resultType=BatchResultType.Failure,
                message="No video IDs or file entries provided for batch update"
            )
            return

        successful_updates = 0
        operations = []
        update_tags: dict[str, tuple[int, bool]] = {}
        no_need_update_flag = False
        new_entries = []

        # Normalize seriesOperation into a {videoId: order} map for id-based lookup.
        series_orders_map: dict[str, int] = {}
        if seriesOperation is not None and not seriesOperation.clear:
            series_orders_map = {entry.videoId: entry.order for entry in seriesOperation.orders}

        try:
            if videoIDs is not None:
                video_models = await VideoModel.find_many(
                    {"_id": {"$in": [ObjectId(str(vid)) for vid in videoIDs]}}
                ).to_list()
                no_need_update_flag = await self._update_existing_videos_operations(
                    video_models,
                    findById=True,
                    author=author,
                    tagsOperation=tagsOperation,
                    update_tags=update_tags,
                    operations=operations,
                    no_need_update_flag=no_need_update_flag,
                    seriesOperation=seriesOperation,
                    seriesOrdersMap=series_orders_map,
                )
                yield self.constructBatchOperationStatus(
                    status=f"Prepared update operations for {len(video_models)} existing videos based on IDs"
                )

            else:
                handler = self.resourceHandlerService.get_handler(category)
                paths = [handler.convert_to_DB_format_path(
                    handler.get_path_standard_format(fe.path)
                ) for fe in fileEntries]
                video_models = await VideoModel.find_many(
                    {"category": category, "path": {"$in": paths}}
                ).to_list()
                existing_paths = {vm.path for vm in video_models}

                no_need_update_flag = await self._update_existing_videos_operations(
                    video_models,
                    findById=False,
                    author=author,
                    tagsOperation=tagsOperation,
                    update_tags=update_tags,
                    operations=operations,
                    no_need_update_flag=no_need_update_flag,
                    seriesOperation=None,
                    seriesOrdersMap={},
                )

                new_entries = [
                    entry for entry in fileEntries
                    if handler.convert_to_DB_format_path(
                        handler.get_path_standard_format(entry.path)
                    ) not in existing_paths
                ]

                if new_entries:
                    new_operations = await asyncio.gather(*[
                        self._process_new_video_entry(
                            entry=entry,
                            category=category,
                            author=author,
                            tagsOperation=tagsOperation,
                            update_tags=update_tags,
                        )
                        for entry in new_entries
                    ])
                    operations.extend(new_operations)
                    yield self.constructBatchOperationStatus(
                        status=f"Prepared update operations for {len(video_models)} existing videos and {len(new_entries)} new videos based on paths"
                    )

            if operations:
                result = await VideoModel.get_pymongo_collection().bulk_write(operations)
                successful_updates = result.modified_count + result.upserted_count

                yield self.constructBatchOperationStatus(
                    status=f"Executed batch update operations: {result.modified_count} modified, {result.upserted_count} upserted"
                )

                await self.tagOperationService.update_tag_counts(update_tags=update_tags)

                if new_entries:
                    handler = self.resourceHandlerService.get_handler(category)
                    new_dir_db_paths = list({
                        handler.dirname(
                            handler.convert_to_DB_format_path(handler.get_path_standard_format(entry.path))
                        )
                        for entry in new_entries
                    })
                    await self.dirMetadataService.batch_update_metadata_forward(category, new_dir_db_paths)

                yield self.constructBatchOperationStatus(
                    resultType=BatchResultType.Success if successful_updates == len(operations) else \
                            BatchResultType.PartialSuccess if successful_updates > 0 else \
                            BatchResultType.Failure,
                    message=f"{successful_updates} out of {len(operations)} updates succeeded" if successful_updates > 0 else None
                )
            elif no_need_update_flag:
                yield self.constructBatchOperationStatus(
                    resultType=BatchResultType.AlreadyUpToDate,
                    message="All videos are already up to date, no updates needed"
                )

        except BulkWriteError as bwe:
            logger.exception(f"Bulk write error during bulk write operation: {bwe.details}")
            raise DatabaseOperationError("batch_update", "bulk_write_failure")
        except Exception as e:
            logger.exception(f"Error during batch update: {e}")
            raise DatabaseOperationError("batch_update", "general_failure")

    async def _update_existing_videos_operations(self,
                                                 video_models: list[VideoModel],
                                                 findById: bool,
                                                 author: str | None,
                                                 tagsOperation: TagsOperationMappingInputModel,
                                                 operations: list[UpdateOne],
                                                 no_need_update_flag: bool,
                                                 update_tags: dict[str, tuple[int, bool]],
                                                 seriesOperation: SeriesOperationInputModel | None,
                                                 seriesOrdersMap: dict[str, int]):
        """
        Helper function to prepare update operations for existing videos based on provided author, tagsOperation, and seriesOperation.
        
        :param video_models: List of video models to prepare update operations for.
        :type video_models: list[VideoModel]
        :param findById: Flag indicating whether to find videos by ID or by path.
        :type findById: bool
        :param author: The new author to set for the videos (optional).
        :type author: str | None
        :param tagsOperation: The tags operation to apply to the videos.
        :type tagsOperation: TagsOperationMappingInputModel
        :param operations: The list to append prepared UpdateOne operations to.
        :type operations: list[UpdateOne]
        :param no_need_update_flag: Flag indicating whether any updates are needed (modified in-place).
        :type no_need_update_flag: bool
        :param update_tags: Dictionary to track tag count changes (modified in-place).
        :type update_tags: dict[str, tuple[int, bool]]
        :param seriesOperation: The series operation to apply to the videos (optional, only applicable when findById is True).
        :type seriesOperation: SeriesOperationInputModel | None
        :param seriesOrdersMap: A mapping of video ID to target series order (only applicable when seriesOperation is provided and clear is False).
        :type seriesOrdersMap: dict[str, int]
        :return: Updated no_need_update_flag indicating whether any updates are needed.
        :rtype: bool
        """
        for video_model in video_models:
            old_tags = set(video_model.tags or [])
            filter_query = {"_id": video_model.id} if findById else {"path": video_model.path}
            update_query = {}

            if author is not None and video_model.author != author:
                update_query["author"] = author

            if tagsOperation is not None:
                # Both directions settle in one pass. The counts move by what actually
                # changed on this video rather than by what was asked for: a tag it
                # already carried is not a new reference, and one it never had is not a
                # lost one.
                new_tags = (old_tags | set(tagsOperation.addTags)) - set(tagsOperation.removeTags)
                self.tagOperationService.track_tag_change(update_tags, new_tags - old_tags, True)
                self.tagOperationService.track_tag_change(update_tags, old_tags - new_tags, False)
                if new_tags != old_tags:
                    update_query["tags"] = list(new_tags)

            if video_model.duration is None or video_model.duration == 0.0:
                handler = self.resourceHandlerService.get_handler(video_model.category)
                video_path = AbsolutePath.from_existing_path(
                    path=video_model.path, 
                    category=video_model.category, 
                    handler=handler
                )
                duration = await self.ffmpegService.get_video_duration(
                    handler=handler,
                    fs_path=video_path.FS_format_path()
                )
                if duration is not None and duration > 0.0:
                    update_query["duration"] = duration

            if seriesOperation is not None:
                if seriesOperation.clear:
                    if video_model.seriesName is not None:
                        update_query["seriesName"] = None
                    if video_model.seriesOrder is not None:
                        update_query["seriesOrder"] = None
                else:
                    target_order = seriesOrdersMap.get(str(video_model.id))
                    if video_model.seriesName != seriesOperation.name:
                        update_query["seriesName"] = seriesOperation.name
                    if video_model.seriesOrder != target_order:
                        update_query["seriesOrder"] = target_order

            if update_query:
                operations.append(UpdateOne(filter_query, {"$set": update_query}))

        if len(operations) == 0 and len(video_models) > 0:
            no_need_update_flag = True

        return no_need_update_flag

    async def _remove_videos_and_update_tags(self, actually_deleted: list[VideoModel], category: str) -> None:
        """
        Helper function to remove video files and update tag counts after videos have been deleted.

        :param actually_deleted: List of video models that were actually deleted from the database.
        :type actually_deleted: list[VideoModel]
        :param category: The category of the deleted videos.
        :type category: str
        """
        paths_to_delete = [v.path for v in actually_deleted]
        await run_in_threadpool(self._remove_videos_by_paths, paths_to_delete, category)

        update_tags: dict[str, tuple[int, bool]] = {}
        for video in actually_deleted:
            self.tagOperationService.track_tag_change(update_tags, set(video.tags or []), False)
        if update_tags:
            await self.tagOperationService.update_tag_counts(update_tags=update_tags)

    def _remove_videos_by_paths(self, paths: list[str], category: str) -> None:
        """
        Helper function to remove video files from the filesystem based on their paths and category.
        
        :param paths: List of video paths to remove.
        :type paths: list[str]
        :param category: The category of the videos to remove.
        :type category: str
        """
        try:
            handler = self.resourceHandlerService.get_handler(category)
            for path in paths:
                handler.delete_file(handler.convert_to_FS_format_path(path))
        except Exception as e:
            logger.exception(f"Error removing video files: {e}")
            raise FileBrowseError("Error removing video files.")

    async def _process_new_video_entry(self,
                                       entry: BaseFileEntry,
                                       category: str,
                                       author: str | None,
                                       tagsOperation: TagsOperationMappingInputModel | None,
                                       update_tags: dict[str, tuple[int,bool]]) -> UpdateOne:
        """
        Helper function to prepare an UpdateOne operation for a new video entry that does not have an existing VideoModel in the database.
        
        :param entry: The file entry representing the new video.
        :type entry: BaseFileEntry
        :param category: The category of the new video.
        :type category: str
        :param author: The author to set for the new video (optional).
        :type author: str | None
        :param tagsOperation: The tags operation to apply to the new video (optional).
        :type tagsOperation: TagsOperationMappingInputModel | None
        :param update_tags: Dictionary to track tag count changes (modified in-place).
        :type update_tags: dict[str, tuple[int,bool]]
        :return: An UpdateOne operation to insert the new video.
        :rtype: UpdateOne
        """
        handler = self.resourceHandlerService.get_handler(category)
        entry_path = AbsolutePath.from_existing_path(
            path=entry.path, 
            category=category, 
            handler=handler
        )
        filter_query = {"path": entry_path.DB_format_path()}

        duration = await self.ffmpegService.get_video_duration(
            handler,
            entry_path.FS_format_path()
        ) or 0.0

        stat = entry.stat()
        # by_alias so the primary key stays "_id", and exclude it so MongoDB assigns one:
        # a plain model_dump() would write a second, always-null "id" field alongside it.
        set_on_insert = VideoModel(
            category=category,
            name=handler.get_filename_without_extension(entry.name),
            path=entry_path.DB_format_path(),
            isDir=False,
            lastModifyTime=stat.mtime,
            size=stat.size,
            duration=duration,
            tags=[]
        ).model_dump(by_alias=True, exclude={"id"})

        if author is not None:
            set_on_insert["author"] = author

        # Only the added tags apply: a document that does not exist yet carries nothing
        # for the removals to take away.
        if tagsOperation is not None and tagsOperation.addTags:
            tags_set = set(tagsOperation.addTags)
            set_on_insert["tags"] = list(tags_set)
            self.tagOperationService.track_tag_change(update_tags, tags_set, True)

        return UpdateOne(filter_query, {"$setOnInsert": set_on_insert}, upsert=True)
