from typing import Optional
from beanie import Document, Indexed, PydanticObjectId, before_event, Insert, Replace
import pymongo

from src.config import get_settings

class VideoModel(Document):
    category: str
    path: Indexed(str, pymongo.ASCENDING, unique=True)  # type: ignore
    isDir: bool
    lastModifyTime: Indexed(float, pymongo.DESCENDING)  # type: ignore
    name: str
    size: float
    tags: list[str]

    author: Optional[str] = "Unknown"
    introduction: Optional[str] = ""
    loved: Optional[bool] = False
    viewCount: Optional[int] = 0
    lastViewTime: Optional[float] = 0.0
    thumbnail: Optional[str] = None
    duration: Optional[float] = 0.0

    # Back-reference to SeriesModel, kept by SeriesService alone; the series' videoIds
    # remain the source of truth for membership and order.
    seriesId: Optional[PydanticObjectId] = None

    @before_event(Insert, Replace)
    def validate_category(self):
        valid = get_settings().get_valid_categories()
        if self.category not in valid:
            raise ValueError(f"Invalid category '{self.category}'. Must be one of {valid}")

    class Settings:
        name = "videos"
        indexes = [
            [("category", pymongo.ASCENDING)],
            [("tags", pymongo.ASCENDING)],
            [("viewCount", pymongo.DESCENDING)],
            [("lastViewTime", pymongo.DESCENDING)],
            [("loved", pymongo.DESCENDING)],
            [("author", pymongo.ASCENDING)],
            # compound index: loved + lastViewTime (used for loved videos)
            [("loved", pymongo.DESCENDING), ("lastViewTime", pymongo.DESCENDING)],
            # compound index: viewCount + lastViewTime (used for popular videos)
            [("viewCount", pymongo.DESCENDING), ("lastViewTime", pymongo.DESCENDING)],
            [("duration", pymongo.DESCENDING)],
            [("seriesId", pymongo.ASCENDING)],
        ]
