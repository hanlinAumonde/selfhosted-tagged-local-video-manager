from beanie import Document, Indexed, before_event, Insert, Replace
import pymongo
from src.config import get_settings

class DirMetadataModel(Document):
    category: str
    path: Indexed(str, pymongo.ASCENDING, unique=True)  # type: ignore
    total_size: float
    last_modified_time: float

    # Whether a user deliberately created this directory. Not derivable from the
    # filesystem, and not from the existence of this document either: metadata is
    # persisted for every directory that gets walked, zero aggregates included. The
    # browser needs it to keep listing a folder someone just made and has yet to fill.
    user_created: bool = False

    # Whether a user deliberately took this directory away. Set when a "Delete all"
    # removed the folder but the storage still holds something else inside it, so the
    # directory is still there and would otherwise come back the moment anything under
    # it aggregates above zero again. It is also what lets a later folder of the same
    # name be created without touching the storage: the directory never left.
    user_deleted: bool = False

    @before_event(Insert, Replace)
    def validate_category(self):
        valid = get_settings().get_valid_categories()
        if self.category not in valid:
            raise ValueError(f"Invalid category '{self.category}'. Must be one of {valid}")

    class Settings:
        name = "dir_metadata"
        indexes = [
            [("category", pymongo.ASCENDING)],
        ]
