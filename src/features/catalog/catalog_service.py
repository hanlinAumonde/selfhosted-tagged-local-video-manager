import time
from dataclasses import dataclass, field
from enum import Enum

from bson import ObjectId
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from src.config import Settings
from src.features.catalog.video import VideoModel
from src.features.catalog.video_tag import VideoTagModel
from src.errors import DatabaseOperationError, InputValidationError, VideoNotFoundError
from src.logger import get_logger
from src.schema.types.pydantic_types.batch_operation_type import SeriesOrderEntryInputModel
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.features.catalog.tag_operation_service import TagOperationService
from src.platform.jobs.path_locks import PathLockRegistry

logger = get_logger("catalog_service")


class VideoSortOption(str, Enum):
    """How a result page is ordered. Published over GraphQL as-is."""
    Latest = "Latest"
    LastUpdate = "LastUpdate"
    MostViewed = "MostViewed"
    Loved = "Loved"
    Longest = "Longest"


class SearchField(str, Enum):
    """Which field an autocomplete request is about."""
    Name = "Name"
    Author = "Author"
    Tag = "Tag"


_DEFAULT_SORT = [("lastModifyTime", -1)]

#: Sort specification per option. Anything unrecognised falls back to newest on disk.
_SORT_BY_OPTION = {
    VideoSortOption.Latest.value: [("lastViewTime", -1)],
    VideoSortOption.LastUpdate.value: _DEFAULT_SORT,
    VideoSortOption.MostViewed.value: [("viewCount", -1), ("lastViewTime", -1)],
    VideoSortOption.Loved.value: [("loved", -1), ("lastViewTime", -1)],
    VideoSortOption.Longest.value: [("duration", -1)],
}


@dataclass(slots=True)
class VideoSearchCriteria:
    """
    What a caller is asking for.

    Page size is decided by the caller rather than here, because it depends on which
    surface is asking — the homepage rails show fewer than the search page.
    """
    page_number: int
    page_size: int
    title_keyword: str | None = None
    author: str | None = None
    tags: list[str] = field(default_factory=list)
    sort_by: str = VideoSortOption.Latest.value


@dataclass(slots=True)
class VideoSearchPage:
    """
    One page of results.

    ``locked_paths`` is resolved once for the whole page rather than per video, so callers
    can mark every row without an extra query each.
    """
    videos: list[VideoModel]
    locked_paths: set[str]
    total_count: int
    page_size: int
    page_number: int


class CatalogService:
    """
    Everything that reads or writes the video catalogue.

    Owns the queries that used to sit inline in the GraphQL resolvers, so the same
    behaviour is reachable from the REST router, a background task, or a test that never
    builds a schema.
    """

    def __init__(
        self,
        settings: Settings,
        tag_operation_service: TagOperationService,
        dir_metadata_service: DirMetadataService,
        resource_handler_service: ResourceHandlerService,
        ffmpeg_service: FFmpegService,
        path_locks: PathLockRegistry,
    ):
        self.settings = settings
        self.tagOperationService = tag_operation_service
        self.dirMetadataService = dir_metadata_service
        self.resourceHandlerService = resource_handler_service
        self.ffmpegService = ffmpeg_service
        self.pathLocks = path_locks

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def search_videos(self, criteria: VideoSearchCriteria) -> VideoSearchPage:
        """
        Run a paged search, backfilling any duration that was never resolved.

        Categories no longer present in the configuration are excluded, so unmounting a
        directory stops surfacing its videos without needing the records deleted.

        :param criteria: The filters, ordering and page to fetch.
        :type criteria: VideoSearchCriteria
        :return: The page, with the locked paths of every row it contains.
        :rtype: VideoSearchPage
        :raises DatabaseOperationError: If the query itself fails.
        """
        valid_categories = self.settings.get_valid_categories()
        if not valid_categories:
            return VideoSearchPage(
                videos=[], locked_paths=set(), total_count=0,
                page_size=criteria.page_size, page_number=criteria.page_number,
            )

        query_filters: dict = {"category": {"$in": valid_categories}}
        if criteria.title_keyword:
            query_filters["name"] = {"$regex": criteria.title_keyword, "$options": "i"}
        if criteria.author:
            query_filters["author"] = {"$regex": criteria.author, "$options": "i"}
        if criteria.tags:
            query_filters["tags"] = {"$all": criteria.tags}
        if criteria.sort_by == VideoSortOption.Loved.value:
            query_filters["loved"] = True

        sort_criteria = _SORT_BY_OPTION.get(criteria.sort_by, _DEFAULT_SORT)
        skip = (criteria.page_number - 1) * criteria.page_size

        try:
            query = VideoModel.find(query_filters)
            total_count = await query.count()
            videos = (
                await query.sort(sort_criteria)
                .skip(skip)
                .limit(criteria.page_size)
                .to_list()
            )
        except Exception as e:
            logger.exception(f"Database operation error during video search: {e}")
            raise DatabaseOperationError(
                operation="video search",
                details=(
                    f"Filters-{query_filters}, Sort-{sort_criteria}, "
                    f"Skip-{skip}, Limit-{criteria.page_size}"
                ),
            )

        for video in videos:
            await self._ensure_duration(video)

        return VideoSearchPage(
            videos=videos,
            locked_paths=await self.pathLocks.locked_paths(v.path for v in videos),
            total_count=total_count,
            page_size=criteria.page_size,
            page_number=criteria.page_number,
        )

    async def suggest(self, field_name: str, keyword: str) -> list[str]:
        """
        Autocomplete one search field.

        Tags come from the tag collection so reference counts decide the ordering; names
        and authors are distinct values aggregated straight off the videos. For tags the
        prefix matches lead and only the remaining slots are filled from matches anywhere
        in the name, so typing "act" offers "action" before "abstract".

        :param field_name: Which field to complete: a ``SearchField`` value.
        :type field_name: str
        :param keyword: What the user has typed. Empty yields the top tags.
        :type keyword: str
        :return: Suggestions, at most the configured limit for that field.
        :rtype: list[str]
        :raises DatabaseOperationError: If the lookup fails.
        """
        limits = self.settings.suggestion_limit
        try:
            if field_name == SearchField.Tag.value:
                return await self._suggest_tags(keyword, limits.tag)

            limit = limits.name if field_name == SearchField.Name.value else limits.author
            return await self._suggest_distinct_values(field_name.lower(), keyword, limit)
        except Exception as e:
            logger.exception(f"Database operation error during get suggestions: {e}")
            raise DatabaseOperationError(
                operation="get suggestions",
                details=f"Keyword-{keyword}, SuggestionType-{field_name}",
            )

    async def _suggest_tags(self, keyword: str, limit: int) -> list[str]:
        """
        Tag completion: prefix matches first, then contains-matches for any slots left.

        :param keyword: What the user has typed.
        :type keyword: str
        :param limit: Maximum suggestions to return.
        :type limit: int
        :return: Tag names, most-used first within each match group.
        :rtype: list[str]
        """
        if not keyword:
            return [tag.name for tag in await self.tagOperationService.get_top_tag_docs(limit)]

        prefix_query = VideoTagModel.find(
            {"name": {"$regex": f"^{keyword}", "$options": "i"}}
        )
        names = [
            tag.name
            for tag in await self.tagOperationService.get_top_tag_docs(limit, prefix_query)
        ]

        if limit - len(names) > 0:
            contains_query = VideoTagModel.find(
                {"name": {"$regex": f".*{keyword}.*", "$options": "i", "$nin": names}}
            )
            names.extend(
                tag.name
                for tag in await self.tagOperationService.get_top_tag_docs(limit, contains_query)
            )

        return names

    @staticmethod
    async def _suggest_distinct_values(db_field: str, keyword: str, limit: int) -> list[str]:
        """
        Distinct values of one video field that contain the keyword.

        :param db_field: The document field to group on.
        :type db_field: str
        :param keyword: Substring to match, case-insensitively.
        :type keyword: str
        :param limit: Maximum suggestions to return.
        :type limit: int
        :return: The distinct values found, empty ones dropped.
        :rtype: list[str]
        """
        pipeline = [
            {"$match": {db_field: {"$regex": keyword, "$options": "i"}}},
            {"$group": {"_id": "$" + db_field}},
            {"$limit": limit},
        ]
        cursor = await VideoModel.get_pymongo_collection().aggregate(pipeline)
        return [doc["_id"] async for doc in cursor if doc.get("_id")]

    async def _get_video_for(self, operation: str, video_id: str) -> VideoModel:
        """
        Fetch a video on behalf of a named operation.

        A lookup failure is reported under the operation the caller invoked rather than
        under the lookup itself, so the error a client sees names what it asked for.

        :param operation: The caller-facing operation name.
        :type operation: str
        :param video_id: The video's ObjectId, as a string.
        :type video_id: str
        :return: The document.
        :rtype: VideoModel
        """
        try:
            return await self.get_video(video_id)
        except DatabaseOperationError:
            raise DatabaseOperationError(operation, f"videoId-{video_id}")

    async def get_video(self, video_id: str) -> VideoModel:
        """
        Fetch one video by id.

        :param video_id: The video's ObjectId, as a string.
        :type video_id: str
        :return: The document.
        :rtype: VideoModel
        :raises VideoNotFoundError: If no video has that id.
        :raises DatabaseOperationError: If the lookup itself fails.
        """
        try:
            video = await VideoModel.get(ObjectId(str(video_id)))
        except Exception as e:
            logger.exception(f"Database operation error during get video by id: {e}")
            raise DatabaseOperationError(
                operation="get video by id", details=f"videoId-{video_id}"
            )

        if video is None:
            logger.warning(f"Video not found: {video_id}")
            raise VideoNotFoundError(str(video_id))
        return video

    async def is_locked(self, db_path: str) -> bool:
        """
        Whether unfinished background work currently holds this path.

        :param db_path: Path in DB format.
        :type db_path: str
        :return: True if the file is spoken for, e.g. mid-migration.
        :rtype: bool
        """
        return await self.pathLocks.is_locked(db_path)

    async def locked_paths(self, db_paths) -> set[str]:
        """
        Which of the given paths unfinished background work currently holds.

        Bulk by design: a list of videos costs one lookup rather than one per row.

        :param db_paths: Paths in DB format.
        :return: The subset that is locked.
        :rtype: set[str]
        """
        return await self.pathLocks.locked_paths(db_paths)

    async def assert_videos_unlocked(self, video_ids: list[str]) -> None:
        """
        Reject a bulk operation that would touch a file being migrated.

        Checked up front for the whole selection rather than per video mid-run, so a batch
        either starts clean or does not start at all.

        :param video_ids: The videos about to be operated on.
        :type video_ids: list[str]
        :rtype: None
        :raises InputValidationError: If any is locked, naming the first one found.
        """
        videos = await VideoModel.find(
            {"_id": {"$in": [ObjectId(vid) for vid in video_ids]}}
        ).to_list()

        locked_paths = await self.pathLocks.locked_paths(v.path for v in videos)
        for video in videos:
            if video.path in locked_paths:
                raise InputValidationError(
                    field="videoIds",
                    issue=f"video '{video.name}' is being migrated and cannot be modified",
                )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def update_metadata(self, validated_input) -> VideoModel:
        """
        Apply a metadata edit, including any series re-ordering it carries.

        Tag reference counts move by the difference between the old and new tag sets, so a
        tag that survives the edit is neither double-counted nor dropped.

        :param validated_input: An already-validated ``UpdateVideoMetadataInputModel``.
        :return: The updated document.
        :rtype: VideoModel
        :raises InputValidationError: If the file is mid-migration, or the series ordering
            is inconsistent.
        :raises DatabaseOperationError: If the write fails.
        """
        video = await self._get_video_for("update_video_metadata", str(validated_input.videoId))

        if await self.is_locked(video.path):
            raise InputValidationError(
                field="videoId", issue="the file is being migrated and cannot be modified"
            )

        old_tags = set(video.tags or [])
        new_tags = set(validated_input.tags or [])
        update_tags: dict[str, tuple[int, bool]] = {
            **{tag: (1, True) for tag in new_tags - old_tags},
            **{tag: (1, False) for tag in old_tags - new_tags},
        }

        if validated_input.name is not None:
            video.name = validated_input.name
        if validated_input.introduction is not None:
            video.introduction = validated_input.introduction
        if validated_input.author is not None:
            video.author = validated_input.author
        if validated_input.loved is not None:
            video.loved = validated_input.loved

        video.tags = validated_input.tags

        # series: None = no change; clear=True = wipe this video only;
        # otherwise (name + orders) = rewrite the whole series ordering
        series_bulk_ops: list[UpdateOne] = []
        if validated_input.series is not None:
            if validated_input.series.clear:
                video.seriesName = None
                video.seriesOrder = None
            else:
                series_bulk_ops = await self._build_series_rewrite_ops(
                    current_video_id=str(video.id),
                    target_series_name=validated_input.series.name,
                    orders=validated_input.series.orders,
                )
                # Reflect the new membership/order on the in-memory model so the returned
                # video shows the change without a reload.
                for entry in validated_input.series.orders:
                    if entry.videoId == str(video.id):
                        video.seriesName = validated_input.series.name
                        video.seriesOrder = entry.order
                        break

        try:
            await video.save()
            if series_bulk_ops:
                await VideoModel.get_pymongo_collection().bulk_write(series_bulk_ops)
        except BulkWriteError as bwe:
            logger.exception(f"Bulk write error during series rewrite: {bwe.details}")
            raise DatabaseOperationError("update_video_metadata", "series_bulk_write_failure")
        except Exception as e:
            logger.exception(f"Database operation error during update video metadata: {e}")
            raise DatabaseOperationError(
                "update_video_metadata", f"videoId-{validated_input.videoId}"
            )

        await self.tagOperationService.update_tag_counts(update_tags=update_tags)
        return video

    @staticmethod
    async def _build_series_rewrite_ops(
        current_video_id: str,
        target_series_name: str,
        orders: list[SeriesOrderEntryInputModel],
    ) -> list[UpdateOne]:
        """
        Build the bulk ops that rewrite a whole series ordering.

        Validated strictly, because one save from the edit panel must not be able to drag
        videos out of a series they belong to: ``orders`` has to be non-empty, contain the
        video being edited, carry no duplicate id or order value, and every other id in it
        must already belong to ``target_series_name``.

        :param current_video_id: The video being edited; saved by the caller, not here.
        :type current_video_id: str
        :param target_series_name: The series all listed videos will belong to.
        :type target_series_name: str
        :param orders: The requested ordering.
        :type orders: list[SeriesOrderEntryInputModel]
        :return: One update per video other than the one being edited.
        :rtype: list[UpdateOne]
        :raises InputValidationError: If the ordering breaks any of the rules above.
        """
        if not orders:
            raise InputValidationError(
                field="series.orders",
                issue="orders must be non-empty when assigning a series",
            )

        id_to_order: dict[str, int] = {}
        seen_orders: set[int] = set()
        for entry in orders:
            if entry.videoId in id_to_order:
                raise InputValidationError(
                    field="series.orders",
                    issue=f"duplicate videoId in orders: {entry.videoId}",
                )
            if entry.order in seen_orders:
                raise InputValidationError(
                    field="series.orders",
                    issue=f"duplicate order value in orders: {entry.order}",
                )
            id_to_order[entry.videoId] = entry.order
            seen_orders.add(entry.order)

        if current_video_id not in id_to_order:
            raise InputValidationError(
                field="series.orders",
                issue="orders must include the current video being edited",
            )

        other_ids = [vid for vid in id_to_order if vid != current_video_id]
        if other_ids:
            try:
                other_object_ids = [ObjectId(vid) for vid in other_ids]
            except Exception:
                raise InputValidationError(
                    field="series.orders", issue="invalid videoId in orders"
                )

            existing_by_id = {
                str(m.id): m
                for m in await VideoModel.find({"_id": {"$in": other_object_ids}}).to_list()
            }
            missing = [vid for vid in other_ids if vid not in existing_by_id]
            if missing:
                raise InputValidationError(
                    field="series.orders", issue=f"videoIds not found: {missing}"
                )
            foreign = [
                vid for vid, m in existing_by_id.items()
                if m.seriesName != target_series_name
            ]
            if foreign:
                raise InputValidationError(
                    field="series.orders",
                    issue=(
                        f"videoIds do not currently belong to series "
                        f"'{target_series_name}': {foreign}"
                    ),
                )

        return [
            UpdateOne(
                {"_id": ObjectId(vid)},
                {"$set": {"seriesName": target_series_name, "seriesOrder": order}},
            )
            for vid, order in id_to_order.items()
            if vid != current_video_id
        ]

    async def record_view(self, video_id: str) -> VideoModel:
        """
        Increment a video's view count and stamp its last-viewed time.

        :param video_id: The video's ObjectId, as a string.
        :type video_id: str
        :return: The updated document.
        :rtype: VideoModel
        :raises VideoNotFoundError: If no video has that id.
        :raises DatabaseOperationError: If the write fails.
        """
        video = await self._get_video_for("record_video_view", video_id)
        video.viewCount = (video.viewCount or 0) + 1
        video.lastViewTime = time.time()

        try:
            await video.save()
        except Exception as e:
            logger.exception(f"Database operation error during record video view: {e}")
            raise DatabaseOperationError("record_video_view", f"videoId-{video_id}")

        return video

    async def delete_video(self, video_id: str) -> None:
        """
        Delete a video record, its file, and the tag counts it contributed to.

        The record goes first: a file left on disk reappears on the next browse, whereas a
        record pointing at a deleted file is a broken row in every listing.

        :param video_id: The video's ObjectId, as a string.
        :type video_id: str
        :rtype: None
        :raises InputValidationError: If the file is mid-migration.
        :raises DatabaseOperationError: If the delete fails.
        """
        video = await self._get_video_for("delete_video", video_id)

        if await self.is_locked(video.path):
            raise InputValidationError(
                field="videoId", issue="the file is being migrated and cannot be deleted"
            )

        handler = self.resourceHandlerService.get_handler(video.category)
        video_path = AbsolutePath.from_existing_path(
            path=video.path, category=video.category, handler=handler
        )
        old_tags = set(video.tags or [])

        try:
            await video.delete()
            await self.tagOperationService.update_tag_counts(
                update_tags={tag: (1, False) for tag in old_tags}
            )

            video_fs_path = video_path.FS_format_path()
            handler.delete_file(video_fs_path)

            directory_path = handler.dirname(video_fs_path)
            if directory_path:
                await self.dirMetadataService.update_directory_metadata_forward(
                    AbsolutePath.from_existing_path(
                        path=directory_path, category=video.category, handler=handler
                    )
                )
        except Exception as e:
            logger.exception(f"Database operation error during delete video: {e}")
            raise DatabaseOperationError("delete_video", f"videoId-{video_id}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _ensure_duration(self, video: VideoModel) -> None:
        """
        Fill in a duration that was never resolved, and persist it.

        Cheap in the common case: only records still missing a duration cost an ffprobe,
        and each one only ever costs it once.

        :param video: The document to top up, updated in place.
        :type video: VideoModel
        :rtype: None
        """
        if video.duration:
            return

        handler = self.resourceHandlerService.get_handler(video.category)
        fs_path = AbsolutePath.from_existing_path(
            path=video.path, category=video.category, handler=handler
        ).FS_format_path()
        video.duration = await self.ffmpegService.get_video_duration(handler, fs_path)
        await video.save()
