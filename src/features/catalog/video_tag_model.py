from beanie import Document
import pymongo
from beanie import Indexed
from pydantic import Field


class VideoTagModel(Document):
    name: Indexed(str, pymongo.ASCENDING, unique=True)  # type: ignore 
    tag_count: int = Field(Indexed(int, pymongo.DESCENDING), alias="count")  # type: ignore

    class Settings:
        name = "tags"