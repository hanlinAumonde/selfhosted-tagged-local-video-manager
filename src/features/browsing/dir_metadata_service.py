from collections.abc import Iterable
from dataclasses import dataclass

from pymongo import UpdateOne

from src.config import Settings
from src.features.browsing.dir_metadata import DirMetadataModel
from src.logger import get_logger
from src.platform.cache.cache_service import CacheService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.resource_handler_service import ResourceHandlerService

logger = get_logger("dir_metadata_service")


@dataclass(slots=True, frozen=True)
class DirFlags:
    """
    What a listing needs to know about a directory that its aggregates cannot say.

    Both answers come from the same document, so they are fetched together: asking them
    one at a time would put two queries on every row of a listing.
    """
    user_created: bool = False
    user_deleted: bool = False


class DirMetadataService:

    def __init__(
        self,
        settings: Settings,
        resource_handler_service: ResourceHandlerService,
        cache_service: CacheService,
    ):
        self.settings = settings
        self.resourceHandlerService = resource_handler_service
        self._cache = cache_service

    def _cache_key(self, category: str, path: str) -> str:
        return f"{category}:{path}"

    async def get_metadata(self, category: str, path: str) -> tuple[float, float] | None:
        """
        Cache-Aside read: cache -> database -> None

        :param category: The category of the directory.
        :type category: str
        :param path: The path of the directory.
        :type path: str
        :return: A tuple containing the total size and last modified time, or None if not found.
        :rtype: tuple[float, float] | None
        """
        cache_key = self._cache_key(category, path)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        doc = await DirMetadataModel.find_one(
            DirMetadataModel.category == category,
            DirMetadataModel.path == path
        )
        if doc is not None:
            result = (doc.total_size, doc.last_modified_time)
            self._cache.set(cache_key, result)
            return result

        return None

    async def set_metadata(self, category: str, path: str, total_size: float, last_modified_time: float) -> None:
        """
        Single upsert to database + update cache.

        :param category: The category of the directory.
        :type category: str
        :param path: The path of the directory.
        :type path: str
        :param total_size: The total size of the directory.
        :type total_size: float
        :param last_modified_time: The last modified time of the directory.
        :type last_modified_time: float
        """
        await DirMetadataModel.get_pymongo_collection().update_one(
            {"category": category, "path": path},
            {"$set": {
                "category": category,
                "path": path,
                "total_size": total_size,
                "last_modified_time": last_modified_time,
            }},
            upsert=True
        )
        self._cache.set(self._cache_key(category, path), (total_size, last_modified_time))

    async def _set_flags(self, category: str, path: str, flags: dict[str, bool]) -> None:
        """
        Write directory flags without disturbing the aggregates.

        Only the named flags are written. Size and mtime go in ``$setOnInsert`` so
        flagging a directory that already has real aggregates does not zero them — the
        caller may be flagging one that is about to be recalculated, or one that already
        was.

        :param category: The category of the directory.
        :type category: str
        :param path: The path of the directory, in DB format.
        :type path: str
        :param flags: The flag fields to write and their values.
        :type flags: dict[str, bool]
        :rtype: None
        """
        await DirMetadataModel.get_pymongo_collection().update_one(
            {"category": category, "path": path},
            {
                "$set": flags,
                "$setOnInsert": {
                    "category": category,
                    "path": path,
                    "total_size": 0.0,
                    "last_modified_time": 0.0,
                },
            },
            upsert=True,
        )

    async def mark_user_created(self, category: str, path: str) -> None:
        """
        Record that a user deliberately created — or deliberately kept — this directory.

        Clearing ``user_deleted`` in the same write is what re-creating a folder over a
        deleted one amounts to: the directory never left the storage, only the listing.

        :param category: The category of the directory.
        :type category: str
        :param path: The path of the directory, in DB format.
        :type path: str
        :rtype: None
        """
        await self._set_flags(
            category, path, {"user_created": True, "user_deleted": False}
        )

    async def mark_user_deleted(self, category: str, path: str) -> None:
        """
        Record that a user deliberately took this directory away.

        ``user_created`` is cleared in the same write: a folder someone kept and then
        deleted must not go on being listed because of the earlier answer.

        :param category: The category of the directory.
        :type category: str
        :param path: The path of the directory, in DB format.
        :type path: str
        :rtype: None
        """
        await self._set_flags(
            category, path, {"user_deleted": True, "user_created": False}
        )

    async def forget(self, category: str, path: str) -> None:
        """
        Drop everything recorded about a directory that no longer exists.

        :param category: The category of the directory.
        :type category: str
        :param path: The path of the directory, in DB format.
        :type path: str
        :rtype: None
        """
        await DirMetadataModel.get_pymongo_collection().delete_one(
            {"category": category, "path": path}
        )
        self._cache.delete(self._cache_key(category, path))

    async def get_flags(self, category: str, paths: Iterable[str]) -> dict[str, DirFlags]:
        """
        Look up the directory flags for a whole listing in one query.

        A listing asks about every sub-directory it found, so this is deliberately
        plural — the per-path form below exists for callers that genuinely hold one path.

        :param category: The category the directories belong to.
        :type category: str
        :param paths: The directory paths, in DB format.
        :type paths: Iterable[str]
        :return: Flags per path; paths with no record map to the default (all false).
        :rtype: dict[str, DirFlags]
        """
        wanted = list(paths)
        if not wanted:
            return {}

        docs = await DirMetadataModel.find(
            {"category": category, "path": {"$in": wanted}}
        ).to_list()
        found = {
            doc.path: DirFlags(
                user_created=doc.user_created, user_deleted=doc.user_deleted
            )
            for doc in docs
        }
        return {path: found.get(path, DirFlags()) for path in wanted}

    async def is_user_created(self, category: str, path: str) -> bool:
        """
        Whether a user deliberately created this directory.

        Read straight from the database: the cache holds only the size/mtime pair, and
        this flag is asked about exactly when that pair is uninformative.

        :param category: The category of the directory.
        :type category: str
        :param path: The path of the directory, in DB format.
        :type path: str
        :return: True if the directory was created through the application.
        :rtype: bool
        """
        return (await self.get_flags(category, [path]))[path].user_created

    async def is_user_deleted(self, category: str, path: str) -> bool:
        """
        Whether a user deliberately took this directory away.

        :param category: The category of the directory.
        :type category: str
        :param path: The path of the directory, in DB format.
        :type path: str
        :return: True if the directory was deleted through the application.
        :rtype: bool
        """
        return (await self.get_flags(category, [path]))[path].user_deleted

    async def bulk_set_metadata(self, category: str, entries: dict[str, tuple[float, float]]) -> None:
        """
        Bulk upsert to database, then batch update cache.

        :param category: The category of the directory.
        :type category: str
        :param entries: A dictionary mapping directory paths to their metadata (total size, last modified time).
        :type entries: dict[str, tuple[float, float]]
        """
        if not entries:
            return

        operations = [
            UpdateOne(
                {"category": category, "path": path},
                {"$set": {
                    "category": category,
                    "path": path,
                    "total_size": total_size,
                    "last_modified_time": last_modified_time,
                }},
                upsert=True
            )
            for path, (total_size, last_modified_time) in entries.items()
        ]

        try:
            await DirMetadataModel.get_pymongo_collection().bulk_write(operations)
        except Exception as e:
            logger.exception(f"Bulk write error during dir metadata upsert: {e}")

        for path, value in entries.items():
            self._cache.set(self._cache_key(category, path), value)

    async def calculate_directory_metadata(self,
                                           directory_path: AbsolutePath,
                                           skipCache: bool = False,
                                           recursiveCalculation: bool = True) -> tuple[float, float]:
        """
        Calculate the total size and last modified time for a directory, with optional cache usage and recursive calculation.
        
        :param directory_path: The absolute path of the directory.
        :type directory_path: AbsolutePath
        :param skipCache: Whether to skip cache when calculating metadata. Default is False.
        :type skipCache: bool
        :param recursiveCalculation: Whether to calculate metadata recursively for subdirectories. Default is True.
        :type recursiveCalculation: bool
        :return: A tuple containing the total size and last modified time of the directory.
        :rtype: tuple[float, float]
        """
        category = directory_path.category
        if category is None:
            return (0.0, 0.0)

        db_path = directory_path.DB_format_path()
        if not skipCache:
            cached = await self.get_metadata(category, db_path)
            if cached is not None:
                return cached

        collected: dict[str, tuple[float, float]] = {}
        result = await self._calculate_directory_metadata_impl(
            directory_path, collected, recursiveCalculation
        )
        collected[db_path] = result
        await self.bulk_set_metadata(category, collected)
        return result

    async def _calculate_directory_metadata_impl(self,
                                           directory_path: AbsolutePath,
                                           collected: dict[str, tuple[float, float]],
                                           recursiveCalculation: bool) -> tuple[float, float]:
        """
        Internal implementation of directory metadata calculation, which can be called recursively.

        :param directory_path: The absolute path of the directory.
        :type directory_path: AbsolutePath
        :param collected: A dictionary to collect metadata results for directories, used for batch updating later.
        :type collected: dict[str, tuple[float, float]]
        :param recursiveCalculation: Whether to calculate metadata recursively for subdirectories.
        :type recursiveCalculation: bool
        :return: A tuple containing the total size and last modified time of the directory.
        :rtype: tuple[float, float]
        """
        total_size = 0.0
        last_modified_time = 0.0
        category = directory_path.category

        try:
            handler = self.resourceHandlerService.get_handler(category)
            with handler.list_directory(directory_path.FS_format_path()) as entries:
                for entry in entries:
                    if entry.is_dir():
                        sub_path = AbsolutePath.from_existing_path(
                            path=entry.path, 
                            category=category, 
                            handler=handler
                        )
                        if recursiveCalculation:
                            dir_size, dir_mtime = await self._calculate_directory_metadata_impl(
                                sub_path, collected, recursiveCalculation
                            )
                        else:
                            dir_size, dir_mtime = await self.get_metadata(category, sub_path.DB_format_path()) or (0.0, 0.0)
                        collected[sub_path.DB_format_path()] = (dir_size, dir_mtime)
                        total_size += dir_size
                        last_modified_time = max(last_modified_time, dir_mtime)
                    elif entry.is_file() and handler.is_video_file(entry.name):
                        stat = entry.stat()
                        total_size += stat.size
                        last_modified_time = max(last_modified_time, stat.mtime)

        except (OSError, Exception):
            logger.exception(f"Error accessing directory {directory_path} to calculate size and last modified time.")
            total_size = -1.0
            last_modified_time = -1.0

        return total_size, last_modified_time

    async def batch_update_metadata_forward(self, category: str, dir_db_paths: list[str]) -> None:
        """
        Collect all parent directories of the given paths, then batch update their metadata.

        :param category: The category of the directories.
        :type category: str
        :param dir_db_paths: A list of directory paths in DB format that need their metadata updated.
        :type dir_db_paths: list[str]
        """
        if not dir_db_paths:
            return

        handler = self.resourceHandlerService.get_handler(category)
        logical_roots = self.settings.get_all_logical_root_paths()

        all_paths: set[str] = set()
        for db_path in dir_db_paths:
            current = db_path
            while current not in all_paths:
                all_paths.add(current)
                if current in logical_roots:
                    break
                parent = handler.dirname(current)
                if not parent or parent == current:
                    break
                current = parent

        for db_path in sorted(all_paths, key=lambda p: p.count('/'), reverse=True):
            abs_path = AbsolutePath.from_existing_path(
                path=db_path, 
                category=category,
                handler=handler
            )
            await self.calculate_directory_metadata(abs_path, skipCache=True, recursiveCalculation=False)

    async def update_directory_metadata_forward(self, directory_path: AbsolutePath) -> None:
        """
        Update metadata for the given directory and all its parent directories.

        :param directory_path: The absolute path of the directory that has been updated.
        :type directory_path: AbsolutePath
        """
        current_path = directory_path
        category = directory_path.category
        if current_path.category in self.settings.get_all_logical_root_paths():
            return
        
        handler = self.resourceHandlerService.get_handler(category)

        while True:
            total_size, last_modified_time = await self.calculate_directory_metadata(
                current_path, skipCache=True, recursiveCalculation=False
            )
            if total_size == -1.0 and last_modified_time == -1.0:
                logger.exception(f"Failed to calculate metadata for {current_path.get_path()}. Stopping forward update.")
                break
            await self.set_metadata(category, current_path.DB_format_path(), total_size, last_modified_time)

            current_db_path = current_path.DB_format_path()
            if current_db_path in self.settings.get_all_logical_root_paths():
                break
            parent = handler.dirname(current_db_path)
            if not parent or parent == current_db_path:
                break
            current_path.update_path(parent)
