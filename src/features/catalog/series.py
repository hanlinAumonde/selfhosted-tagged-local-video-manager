from beanie import Document, Indexed, PydanticObjectId
import pymongo


class SeriesModel(Document):
    name: Indexed(str, pymongo.ASCENDING, unique=True)  # type: ignore
    # Membership and order in one place: a video's position is its index here, so there
    # is no stored number to drift, and leaving a series closes the gap by itself.
    videoIds: list[PydanticObjectId] = []

    class Settings:
        name = "series"
