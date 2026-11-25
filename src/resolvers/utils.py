from bson import ObjectId
import strawberry

from src.context import ContextEnum, get_context_value
from src.errors import InputValidationError

from src.features.browsing.browse_file_service import BrowseEntry, DirectoryEntry, VideoEntry
from src.features.catalog.catalog_service import CatalogService
from src.features.catalog.series_service import SeriesPlacement, SeriesService
from src.features.migration.migration_batch import MigrationBatchService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.schema.types.fileBrowse_type import FileBrowseNode
from src.schema.types.migration_type import MigrationBatchSummary
from src.schema.types.video_type import Video

def validate_input(input, logger, name: str):
    """
    Validate the input data and return the validated object.

    :param input: The input data, typically a Strawberry input type which contains a `to_pydantic` method.
    :type input: Any
    :param logger: The `loguru` logger instance to log validation errors.
    :type logger: Logger
    :param name: The name of the input field for error reporting.
    :type name: str
    """
    try:
        return input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field=name, issue="Invalid input data")

async def resolve_source_path(video_id: str, info: strawberry.Info) -> AbsolutePath:
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
    video = await catalog_service.get_video(video_id)
    
    handler_service: ResourceHandlerService = get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE)
    handler = handler_service.get_handler(video.category)
    return AbsolutePath.from_existing_path(video.path, category=video.category, handler=handler)

def target_dir_of(validated, info: strawberry.Info) -> AbsolutePath:
    """
    Resolve the target directory a validated migration input names.

    :param validated: Any validated migration input with a ``target_dir_relative_path``.
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :rtype: AbsolutePath
    """
    return AbsolutePath.from_relative_path(
        parsedPath=validated.target_dir_relative_path.parsedPath,
        handlerService=get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE),
        settings=get_context_value(info, ContextEnum.SETTINGS),
    )

async def summary_of(batches: MigrationBatchService, batch_id: str) -> MigrationBatchSummary:
    """
    The published summary of a batch.

    :param batches: The batch service to summarise with.
    :type batches: MigrationBatchService
    :param batch_id: The batch to summarise.
    :type batch_id: str
    :raises InputValidationError: If no such batch exists.
    :rtype: MigrationBatchSummary
    """
    summary = await batches.summarize(batch_id)
    if summary is None:
        raise InputValidationError(field="batch_id", issue="batch does not exist")
    return MigrationBatchSummary.from_service(summary)

async def series_positions(info: strawberry.Info, video_models: list) -> dict[str, SeriesPlacement]:
    """
    The series placement of each given video, in one lookup.

    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :param video_models: The videos to place.
    :type video_models: list[VideoModel]
    :return: Placement by video id; a video in no series has no entry.
    :rtype: dict[str, SeriesPlacement]
    """
    seriesService: SeriesService = get_context_value(info, ContextEnum.SERIES_SERVICE)
    return await seriesService.positions_of(video_models)


async def to_browse_nodes(entries: list[BrowseEntry], info: strawberry.Info) -> list[FileBrowseNode]:
    """
    Present a listing, resolving the series position of every video row in one lookup.

    :param entries: The listing, in the order it is shown.
    :type entries: list[BrowseEntry]
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :rtype: list[FileBrowseNode]
    """
    positions = await series_positions(
        info, [e.document for e in entries if isinstance(e, VideoEntry)]
    )
    return [await to_browse_node(entry, positions) for entry in entries]


async def to_browse_node(
    entry: BrowseEntry, positions: dict[str, SeriesPlacement]
) -> FileBrowseNode:
    """
    Present one directory-listing entry as the GraphQL node the frontend consumes.

    The schema models both rows as a ``Video``, so a directory is given a throwaway
    ObjectId to satisfy the non-null ``id`` field. That is a quirk of this transport and
    stays here: the browse service deals in directories and documents, and has no reason
    to mint identifiers for things that do not have one.

    :param entry: A directory or video row produced by ``BrowseFileService``.
    :type entry: BrowseEntry
    :param positions: Series placements for the listing's videos, keyed by video id.
    :type positions: dict[str, SeriesPlacement]
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
            series=positions.get(str(entry.document.id)),
        )
    )

async def to_video(video_model, info: strawberry.Info) -> Video:
    """
    Present one video document, with its series placement.

    :param video_model: The video to present.
    :type video_model: VideoModel
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :rtype: Video
    """
    seriesService: SeriesService = get_context_value(info, ContextEnum.SERIES_SERVICE)
    positions = await seriesService.positions_of([video_model])
    return await Video.from_mongoDB(video_model, series=positions.get(str(video_model.id)))