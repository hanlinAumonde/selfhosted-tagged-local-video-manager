from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from src.config import Settings
from src.features.catalog.video_tag_model import VideoTagModel
from src.logger import get_logger

logger = get_logger("tag_operation_service")

class TagOperationService:

    def __init__(self, settings: Settings):
        self.settings = settings

    async def get_top_tag_docs(self, limit: int, findQuery=None) -> list[VideoTagModel]:
        """
        Get the top tags sorted by count in descending order, with an optional custom query.

        :param limit: The maximum number of top tags to retrieve.
        :type limit: int
        :param findQuery: Optional custom query to filter tags.
        :type findQuery: Optional[dict]
        :return: A list of top VideoTagModel instances.
        :rtype: list[VideoTagModel]
        """
        if len(self.settings.get_valid_categories()) == 0:
            return []
        if not findQuery:
            findQuery = VideoTagModel.find()
        return await findQuery.sort([("count", -1)]).limit(limit).to_list()
    
    async def update_tag_counts(self, update_tags: dict[str, tuple[int,bool]]) -> None:
        """
        update the tag counts in the database based on the changes in tags using bulk write.

        :param update_tags: Dictionary mapping tag names to a tuple of (count change, is_increment).
        :type update_tags: dict[str, tuple[int,bool]]
        :return: None
        :rtype: None
        """
        operations = []

        for tag_name, (count_change, is_increment) in update_tags.items():
            if is_increment:
                operations.append(
                    UpdateOne(
                        {"name": tag_name},
                        {"$inc": {"count": count_change}},
                        upsert=True
                    )
                )
            else:
                operations.append(
                    UpdateOne(
                        {"name": tag_name},
                        {"$inc": {"count": -count_change}}
                    )
                )

        try:
            if operations:
                await VideoTagModel.get_pymongo_collection().bulk_write(operations)

            # delete tags with non-positive counts
            decremented_tags = [tag for tag, (_, is_inc) in update_tags.items() if not is_inc]
            if decremented_tags:
                await VideoTagModel.find({"count": {"$lte": 0}}).delete()
        
        except BulkWriteError as bwe:
            logger.exception(f"Bulk write error during tag counts update: {bwe.details}")
        except Exception as e:
            logger.exception(f"Error during bulk update of tag counts: {e}")

    def track_tag_change(self, update_tags: dict[str, tuple[int, bool]], tags: set[str], is_increment: bool) -> None:
        """
        Helper function to track changes in tags for batch operations. It updates the update_tags dictionary with the count changes for each tag.
        
        :param update_tags: Dictionary mapping tag names to a tuple of (count change, is_increment).
        :type update_tags: dict[str, tuple[int, bool]]
        :param tags: Set of tags to update.
        :type tags: set[str]
        :param is_increment: Whether to increment (True) or decrement (False) the tag counts.
        :type is_increment: bool
        """
        for tag in tags:
            tag_record: tuple[int, bool] | None = update_tags.get(tag)
            update_tags[tag] = (tag_record[0] + 1, is_increment) if tag_record else (1, is_increment)