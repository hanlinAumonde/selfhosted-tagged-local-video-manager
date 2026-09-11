from typing import Optional
import strawberry

from src.features.catalog.video import VideoModel
from src.features.catalog.video_tag import VideoTagModel
from src.schema.types.pydantic_types.batch_operation_type import SeriesOrderEntryInputModel
from src.schema.types.pydantic_types.video_type import (
    SeriesFieldInputModel,
    UpdateVideoMetadataInputModel,
)

@strawberry.type
class VideoTag:
    name: str
    count: int

@strawberry.type
class Video:
    id: strawberry.ID
    isDir: bool
    viewCount: int
    lastViewTime: float
    lastModifyTime: float
    name: str
    introduction: str
    author: str
    loved: bool
    size: float
    tags: list[VideoTag]
    duration: float

    # if None use default thumbnail in public/static/default_thumbnail.jpg
    thumbnail: Optional[str] = None

    seriesName: Optional[str] = None
    seriesOrder: Optional[int] = None

    # True while a migration task holds this file. The frontend disables every action on
    # a locked video; the backend enforces the same rule in its mutations.
    isLocked: bool = False

    # Where this row was found, relative to the directory that was asked about. Null for
    # an ordinary listing, whose rows are all in that directory; set for a search result,
    # which may come from any depth below it.
    relativePath: Optional[str] = None

    @classmethod
    async def from_mongoDB(
        cls,
        videoModel: VideoModel,
        getTagsCount: bool = False,
        isLocked: bool = False,
        relativePath: Optional[str] = None,
    ) -> "Video":
        """
        Convert a VideoModel instance from MongoDB to a Video GraphQL type.

        :param videoModel: The source document.
        :type videoModel: VideoModel
        :param getTagsCount: Whether to look up reference counts for the video's tags.
        :type getTagsCount: bool
        :param isLocked: Whether a migration task currently holds this file. Passed in
            rather than queried here, so a list of videos costs one lookup instead of N —
            see ``find_locked_paths``.
        :type isLocked: bool
        :param relativePath: The sub-directory this row was found in, relative to the
            directory that was asked about. Only a search has one.
        :type relativePath: Optional[str]
        :return: The GraphQL representation.
        :rtype: Video
        """
        tag_names = videoModel.tags or []

        if tag_names and getTagsCount:
            tag_models = await VideoTagModel.find({"name": {"$in": tag_names}}).to_list()
            tag_dict = {tag.name: tag.tag_count for tag in tag_models}
        else:
            tag_dict = {}

        return cls(
            id=str(videoModel.id),
            isDir=videoModel.isDir,
            viewCount=videoModel.viewCount or 0,
            lastViewTime=videoModel.lastViewTime or 0.0,
            lastModifyTime=videoModel.lastModifyTime,
            name=videoModel.name,
            introduction=videoModel.introduction or "",
            author=videoModel.author or "Unknown",
            loved=videoModel.loved or False,
            size=int(videoModel.size),
            tags=[
                VideoTag(name=tag_name, count=tag_dict.get(tag_name, 0))
                for tag_name in tag_names
            ],
            thumbnail=videoModel.thumbnail,
            duration=videoModel.duration or 0.0,
            seriesName=videoModel.seriesName,
            seriesOrder=videoModel.seriesOrder,
            isLocked=isLocked,
            relativePath=relativePath,
        )
    
    @classmethod
    def create_new(cls, id: strawberry.ID, name: str, isDir: bool, lastModifyTime: float, size: float, duration: float = 0.0) -> "Video":
        """
        Create a new Video instance with default values.
        """
        return cls(
            id=id,
            isDir=isDir,
            viewCount=0,
            lastViewTime=0.0,
            lastModifyTime=lastModifyTime,
            name=name,
            introduction="",
            author="Unknown",
            loved=False,
            size=size,
            tags=[],
            thumbnail=None,
            duration=duration,
            seriesName=None,
            seriesOrder=None,
        )


@strawberry.experimental.pydantic.input(model=SeriesOrderEntryInputModel)
class SeriesOrderEntryInput:
    videoId: strawberry.auto
    order: strawberry.auto


@strawberry.experimental.pydantic.input(model=SeriesFieldInputModel)
class SeriesFieldInput:
    name: strawberry.auto
    clear: strawberry.auto
    orders: list[SeriesOrderEntryInput] = strawberry.field(default_factory=list)


@strawberry.experimental.pydantic.input(model=UpdateVideoMetadataInputModel)
class UpdateVideoMetadataInput:
    videoId: strawberry.auto
    name: strawberry.auto
    introduction: strawberry.auto
    author: strawberry.auto
    tags: strawberry.auto
    loved: strawberry.auto
    series: Optional[SeriesFieldInput] = None