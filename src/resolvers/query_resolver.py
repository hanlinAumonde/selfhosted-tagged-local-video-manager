import strawberry
from bson import ObjectId

from src.config import Settings
from src.context import ContextEnum, get_context_value
from src.errors import DatabaseOperationError, InputValidationError
from src.logger import get_logger
from src.schema.types.fileBrowse_type import (
    FileBrowseNode,
    RelativePathInput,
    SearchInDirectoryInput
)
from src.schema.types.search_type import (
    DirectoryMetadataResult,
    SearchFrom,
    SuggestionInput,
    VideoSearchInput,
    VideoSearchResult,
    Pagination
)
from src.schema.types.video_type import Video, VideoTag
from src.features.browsing.browse_file_service import (
    BrowseEntry,
    BrowseFileService,
    DirectoryEntry,
    DirectorySearchCriteria
)
from src.features.catalog.catalog_service import CatalogService, VideoSearchCriteria
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.storage.absolute_path import AbsolutePath
from src.features.catalog.series_service import SeriesService
from src.features.catalog.tag_operation_service import TagOperationService

logger = get_logger("query_resolver")
    
async def resolve_search_videos(input: VideoSearchInput, info: strawberry.Info) -> VideoSearchResult:
    """
    Resolve function to search for videos based on various criteria.

    :param input: Filter criteria for searching videos.
    :type input: VideoSearchInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: Search results for videos.
    :rtype: VideoSearchResult
    """
    try:
        validated_input = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="VideoSearchInput", issue="Invalid input data for video search")

    settings: Settings = get_context_value(info, ContextEnum.SETTINGS)
    catalogService: CatalogService = get_context_value(info, ContextEnum.CATALOG_SERVICE)

    if validated_input.fromPage == SearchFrom.FrontalPage.value:
        page_size = settings.page_size_default.homepage_videos
    else:
        page_size = settings.page_size_default.searchpage

    page = await catalogService.search_videos(
        VideoSearchCriteria(
            page_number=validated_input.currentPageNumber or 1,
            page_size=page_size,
            title_keyword=validated_input.titleKeyword.keyWord,
            author=validated_input.author.keyWord,
            tags=validated_input.tags or [],
            sort_by=validated_input.sortBy,
        )
    )

    return VideoSearchResult(
        pagination=Pagination(
            size=page.page_size,
            totalCount=page.total_count,
            currentPageNumber=page.page_number,
        ),
        videos=[
            await Video.from_mongoDB(video, isLocked=video.path in page.locked_paths)
            for video in page.videos
        ],
    )

async def resolve_get_top_tags(info: strawberry.Info) -> list[VideoTag]:
    """
    Resolve function to retrieve the top video tags.

    :return: List of top video tags.
    :rtype: list[VideoTag]
    """
    settings: Settings = get_context_value(info, ContextEnum.SETTINGS)
    tagOperationService: TagOperationService = get_context_value(info, ContextEnum.TAG_OPERATION_SERVICE)
    limit = settings.page_size_default.homepage_tags
    try:
        tag_docs = await tagOperationService.get_top_tag_docs(limit)
        return [VideoTag(name=tag.name, count=tag.tag_count) for tag in tag_docs]
    except Exception as e:
        logger.exception(f"Database operation error during get top tags: {e}")
        raise DatabaseOperationError(operation="get top tags",
                                        details=f"Limit-{limit}")

async def resolve_get_suggestions(input: SuggestionInput, info: strawberry.Info) -> list[str]:
    """
    Resolve function to get suggestions based on a keyword and suggestion type.

    :param input: Input containing the keyword and suggestion type.
    :type input: SuggestionInput
    :return: Suggestion results.
    :rtype: SuggestionResults
    """
    try:             
        validated_input = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="SuggestionInput", issue="Invalid input data for suggestions")

    if not validated_input.keyword.keyWord:
        return []

    catalogService: CatalogService = get_context_value(info, ContextEnum.CATALOG_SERVICE)
    return await catalogService.suggest(
        field_name=validated_input.suggestionType,
        keyword=validated_input.keyword.keyWord,
    )

async def resolve_get_video_by_id(videoId: strawberry.ID, info: strawberry.Info) -> Video:
    """
    Resolve function to retrieve a video by its ID.

    :param videoId: The ID of the video to retrieve.
    :type videoId: strawberry.ID
    :return: The video corresponding to the given ID.
    :rtype: Video
    """
    catalogService: CatalogService = get_context_value(info, ContextEnum.CATALOG_SERVICE)
    video_model = await catalogService.get_video(str(videoId))

    # Returned rather than refused: the player page needs the metadata in order to show
    # why playback is unavailable.
    return await Video.from_mongoDB(
        video_model, isLocked=await catalogService.is_locked(video_model.path)
    )

async def resolve_browse_directory(input: RelativePathInput, info: strawberry.Info) -> list[FileBrowseNode]:
    """
    Resolve function to browse videos in a directory specified by a relative path.

    :param input: The relative path input to browse.
    :type input: RelativePathInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: List of file browse nodes in the specified directory.
    :rtype: list[FileBrowseNode]
    """
    try:
        relativePathInputModel = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="RelativePathInput", issue="Invalid input data for directory browsing")

    browseFileService: BrowseFileService = get_context_value(info, ContextEnum.BROWSE_FILE_SERVICE)
    entries = await browseFileService.get_node_list_in_directory(
        AbsolutePath.from_relative_path(
            parsedPath=relativePathInputModel.parsedPath,
            handlerService=get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE),
            settings=get_context_value(info, ContextEnum.SETTINGS)
        ),
        skipCache=relativePathInputModel.skipCache,
        recursiveCalculation=relativePathInputModel.recursiveCalculation
    )
    return [await _to_browse_node(entry) for entry in entries]


async def resolve_search_in_directory(input: SearchInDirectoryInput, info: strawberry.Info) -> list[FileBrowseNode]:
    """
    Resolve function to search the catalogued videos under a directory and everything
    below it, by name, author and tags.

    Results are published as ``FileBrowseNode`` — the same shape ``browseDirectory``
    returns — so the frontend renders them through the table it already has, with every
    row action working as it does in an ordinary listing.

    :param input: The directory to search and the fields to match.
    :type input: SearchInDirectoryInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: List of file browse nodes matching the search.
    :rtype: list[FileBrowseNode]
    """
    try:
        validated_input = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="SearchInDirectoryInput", issue="Invalid input data for directory search")

    browseFileService: BrowseFileService = get_context_value(info, ContextEnum.BROWSE_FILE_SERVICE)
    entries = await browseFileService.search_videos_in_directory(
        AbsolutePath.from_relative_path(
            parsedPath=validated_input.path.parsedPath,
            handlerService=get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE),
            settings=get_context_value(info, ContextEnum.SETTINGS)
        ),
        DirectorySearchCriteria(
            name=validated_input.name.keyWord,
            author=validated_input.author.keyWord,
            tags=validated_input.tags,
        )
    )
    return [await _to_browse_node(entry) for entry in entries]


async def _to_browse_node(entry: BrowseEntry) -> FileBrowseNode:
    """
    Present one directory-listing entry as the GraphQL node the frontend consumes.

    The schema models both rows as a ``Video``, so a directory is given a throwaway
    ObjectId to satisfy the non-null ``id`` field. That is a quirk of this transport and
    stays here: the browse service deals in directories and documents, and has no reason
    to mint identifiers for things that do not have one.

    :param entry: A directory or video row produced by ``BrowseFileService``.
    :type entry: BrowseEntry
    :return: The node in its published shape.
    :rtype: FileBrowseNode
    """
    if isinstance(entry, DirectoryEntry):
        return FileBrowseNode(
            node=Video.create_new(
                id=strawberry.ID(str(ObjectId())),
                name=entry.name,
                isDir=True,
                lastModifyTime=entry.last_modify_time,
                size=entry.size,
            )
        )

    return FileBrowseNode(
        node=await Video.from_mongoDB(
            entry.document,
            getTagsCount=False,
            isLocked=entry.is_locked,
            # Empty means "in the directory that was asked about", which is every row of
            # an ordinary listing — published as null rather than as an empty string.
            relativePath=entry.relative_dir or None,
        )
    )

async def resolve_search_series_by_prefix(prefix: str, limit: int, info: strawberry.Info) -> list[str]:
    """
    Resolve function to look up series names containing the given keyword (case-insensitive),
    with names starting with it ranked first. Used for the autocomplete dropdown in the video
    edit panel.

    :param prefix: The keyword to search for; matched anywhere in the series name.
    :type prefix: str
    :param limit: The maximum number of series names to return.
    :type limit: int
    :return: List of series names matching the keyword.
    :rtype: list[str]
    """
    if limit <= 0:
        return []
    try:
        seriesService: SeriesService = get_context_value(info, ContextEnum.SERIES_SERVICE)
        return await seriesService.search_by_prefix(prefix or "", limit)
    except Exception as e:
        logger.exception(f"Database operation error during search series by prefix: {e}")
        raise DatabaseOperationError(operation="search series by prefix",
                                        details=f"Prefix-{prefix}, Limit-{limit}")

async def resolve_get_series_videos(name: str, info: strawberry.Info) -> list[Video]:
    """
    Resolve function to retrieve all videos belonging to a series, ordered by seriesOrder
    ascending. Videos outside the currently configured categories are excluded.

    :param name: The name of the series to retrieve videos for.
    :type name: str
    :return: List of videos in the specified series.
    :rtype: list[Video]
    """
    if not name:
        return []
    try:
        settings: Settings = get_context_value(info, ContextEnum.SETTINGS)
        seriesService: SeriesService = get_context_value(info, ContextEnum.SERIES_SERVICE)
        valid_categories = settings.get_valid_categories()
        video_models = await seriesService.get_videos_in_series(name, valid_categories)
        catalogService: CatalogService = get_context_value(info, ContextEnum.CATALOG_SERVICE)
        locked_paths = await catalogService.locked_paths(vm.path for vm in video_models)
        return [
            await Video.from_mongoDB(vm, isLocked=vm.path in locked_paths)
            for vm in video_models
        ]
    except Exception as e:
        logger.exception(f"Database operation error during get series videos: {e}")
        raise DatabaseOperationError(operation="get series videos", details=f"Name-{name}")

async def resolve_directory_metadata(input: RelativePathInput, info: strawberry.Info) -> DirectoryMetadataResult:
    """
    Resolve function to get metadata of a directory specified by a relative path.

    :param input: The relative path input of the directory.
    :type input: RelativePathInput
    :return: Directory metadata result containing total size and last modified time.
    :rtype: DirectoryMetadataResult
    """
    try:
        relativePathInputModel = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="RelativePathInput", issue="Invalid input data for directory metadata")
    
    abs_path = AbsolutePath.from_relative_path(
        parsedPath=relativePathInputModel.parsedPath,
        handlerService=get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE),
        settings=get_context_value(info, ContextEnum.SETTINGS)
    )
    if abs_path.is_root_level() or abs_path.is_category_level():
        return DirectoryMetadataResult(
            totalSize=0.0,
            lastModifiedTime=0.0
        )
    dirMetadataService: DirMetadataService = get_context_value(info, ContextEnum.DIR_METADATA_SERVICE)
    size, last_update_time = await dirMetadataService.calculate_directory_metadata(
        abs_path,
        skipCache=True,
        recursiveCalculation=True
    )

    return DirectoryMetadataResult(
        totalSize=size,
        lastModifiedTime=last_update_time
    )