import strawberry

from src.context import ContextEnum, get_context_value
from src.errors import InputValidationError
from src.logger import get_logger
from src.schema.types.fileBrowse_type import (
    CreateDirectoryInput,
    DirectoryMutationResult,
    VideoMutationResult
)
from src.schema.types.video_type import UpdateVideoMetadataInput, Video
from src.features.browsing.browse_file_service import BrowseFileService
from src.features.catalog.catalog_service import CatalogService
from src.platform.storage.absolute_path import AbsolutePath

logger = get_logger("mutation_resolver")


async def resolve_update_video_metadata(input: UpdateVideoMetadataInput, info: strawberry.Info) -> VideoMutationResult:
    """
    Resolve function to update the metadata of a video.

    :param input: Input containing the video ID and new metadata.
    :type input: UpdateVideoMetadataInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: VideoMutationResult containing a success flag and the updated video.
    :rtype: VideoMutationResult
    """
    try:
        validated_input = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="UpdateVideoMetadataInput", issue="Invalid input data for updating video metadata")

    catalogService: CatalogService = get_context_value(info, ContextEnum.CATALOG_SERVICE)
    video_model = await catalogService.update_metadata(validated_input)
    return VideoMutationResult(success=True, video=await Video.from_mongoDB(video_model))


async def resolve_record_video_view(videoId: strawberry.ID, info: strawberry.Info) -> VideoMutationResult:
    """
    Resolve function to record a view for a video.

    :param videoId: The ID of the video to record a view for.
    :type videoId: strawberry.ID
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: VideoMutationResult containing the video with its updated view count.
    :rtype: VideoMutationResult
    """
    catalogService: CatalogService = get_context_value(info, ContextEnum.CATALOG_SERVICE)
    video_model = await catalogService.record_view(str(videoId))
    return VideoMutationResult(success=True, video=await Video.from_mongoDB(video_model))


async def resolve_delete_video(videoId: strawberry.ID, info: strawberry.Info) -> VideoMutationResult:
    """
    Resolve function to delete a video by its ID.

    :param videoId: The ID of the video to delete.
    :type videoId: strawberry.ID
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: VideoMutationResult flagging success; no video is returned, it is gone.
    :rtype: VideoMutationResult
    """
    catalogService: CatalogService = get_context_value(info, ContextEnum.CATALOG_SERVICE)
    await catalogService.delete_video(str(videoId))
    return VideoMutationResult(success=True, video=None)


async def resolve_create_directory(input: CreateDirectoryInput, info: strawberry.Info) -> DirectoryMutationResult:
    """
    Resolve function to create a directory inside the directory being browsed.

    :param input: Input containing the parent directory path and the new folder name.
    :type input: CreateDirectoryInput
    :param info: Strawberry GraphQL info object.
    :type info: strawberry.Info
    :return: DirectoryMutationResult naming the directory that now exists.
    :rtype: DirectoryMutationResult
    """
    try:
        validated_input = input.to_pydantic()
    except Exception as e:
        logger.exception(f"Input validation error: {e}")
        raise InputValidationError(field="CreateDirectoryInput", issue="Invalid input data for creating a directory")

    browseFileService: BrowseFileService = get_context_value(info, ContextEnum.BROWSE_FILE_SERVICE)
    db_path = await browseFileService.create_directory(
        AbsolutePath.from_relative_path(
            parsedPath=validated_input.parentPath.parsedPath,
            handlerService=get_context_value(info, ContextEnum.RESOURCE_HANDLER_SERVICE),
            settings=get_context_value(info, ContextEnum.SETTINGS)
        ),
        validated_input.name
    )
    return DirectoryMutationResult(success=True, name=validated_input.name, path=db_path)
