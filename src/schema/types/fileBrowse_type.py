from typing import Annotated, Optional
import strawberry

from src.schema.types.pydantic_types.fileBrowe_type import (
    CreateDirectoryInputModel,
    RelativePathInputModel,
    SearchInDirectoryInputModel
)
from src.schema.types.search_type import SerachKeyword
from src.schema.types.pydantic_types.batch_operation_type import (
    SeriesOperationInputModel,
    TagsOperationMappingInputModel,
    VideosBatchOperationInputModel
)
from src.schema.types.video_type import SeriesOrderEntryInput, Video
from src.features.browsing.batch_operation_service import BatchProgress, BatchResultType
from src.features.browsing.directory_deletion import DirectoryDeletionStrategy

BatchResultTypeEnum = Annotated[BatchResultType, strawberry.enum]
DirectoryDeletionStrategyEnum = Annotated[DirectoryDeletionStrategy, strawberry.enum]

@strawberry.type
class FileBrowseNode:
    node: Video

@strawberry.experimental.pydantic.input(model=RelativePathInputModel)
class RelativePathInput:
    skipCache: strawberry.auto
    recursiveCalculation: strawberry.auto
    relativePath: strawberry.auto
    parsedPath: strawberry.auto


@strawberry.experimental.pydantic.input(model=SearchInDirectoryInputModel)
class SearchInDirectoryInput:
    path: RelativePathInput
    name: SerachKeyword
    author: SerachKeyword
    tags: strawberry.auto


@strawberry.experimental.pydantic.input(model=CreateDirectoryInputModel)
class CreateDirectoryInput:
    parentPath: RelativePathInput
    name: strawberry.auto


@strawberry.experimental.pydantic.input(model=TagsOperationMappingInputModel)
class TagsOperationMappingInput:
    addTags: strawberry.auto
    removeTags: strawberry.auto


@strawberry.experimental.pydantic.input(model=SeriesOperationInputModel)
class SeriesOperationInput:
    name: strawberry.auto
    clear: strawberry.auto
    orders: list[SeriesOrderEntryInput] = strawberry.field(default_factory=list)


@strawberry.experimental.pydantic.input(model=VideosBatchOperationInputModel)
class VideosBatchOperationInput:
    videoIds: strawberry.auto
    relativePath: RelativePathInput
    tagsOperation: Optional[TagsOperationMappingInput] = None
    author: strawberry.auto
    seriesOperation: Optional[SeriesOperationInput] = None
    directoryDeletion: Optional[DirectoryDeletionStrategyEnum] = None

@strawberry.type
class VideosBatchOperationResult:
    resultType: BatchResultTypeEnum
    message: Optional[str] = None

@strawberry.type
class BatchOperationStatus:
    result: Optional[VideosBatchOperationResult]
    status: Optional[str] = None

    @classmethod
    def from_service(cls, progress: BatchProgress) -> "BatchOperationStatus":
        """
        Present one batch progress report in its published shape.

        :param progress: Report emitted by ``BatchOperationService``.
        :type progress: BatchProgress
        :return: The report as the schema exposes it.
        :rtype: BatchOperationStatus
        """
        if progress.result_type is None or progress.message is None:
            return cls(result=None, status=progress.status)
        return cls(
            result=VideosBatchOperationResult(
                resultType=progress.result_type,
                message=progress.message,
            ),
            status=progress.status,
        )

@strawberry.type
class VideoMutationResult:
    success: bool
    video: Optional[Video] = None

@strawberry.type
class DirectoryMutationResult:
    """A directory that now exists. Carries no ``Video``: a directory has no document."""
    success: bool
    name: str
    path: str