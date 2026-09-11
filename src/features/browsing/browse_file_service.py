import asyncio
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pymongo import UpdateOne

from src.config import Settings
from src.features.catalog.video import VideoModel
from src.errors import DatabaseOperationError, FileBrowseError, InputValidationError
from src.logger import get_logger
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.media.ffmpeg_service import FFmpegService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.base_file_entry import BaseFileEntry
from src.platform.storage.base_resource_handler import BaseResourceHandler
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.platform.jobs.path_locks import PathLockRegistry

logger = get_logger("browse_file_service")


@dataclass(slots=True)
class _PendingVideo:
    """A video file seen while walking a directory, awaiting its database document."""
    db_path: str
    fs_path: str
    name: str
    mtime: float
    size: float


@dataclass(slots=True)
class DirectoryEntry:
    """
    A sub-directory in a listing, described by the aggregate of what it contains.

    Has no database document of its own: directories are not tracked in the videos
    collection, they are summarised on the fly from ``DirMetadataService``.
    """
    name: str
    size: float
    last_modify_time: float


@dataclass(slots=True)
class VideoEntry:
    """
    A video file in a listing, paired with whether unfinished background work holds it.

    ``is_locked`` is resolved in bulk for the whole directory rather than per file, so it
    is carried here instead of being looked up again downstream.

    ``relative_dir`` is empty for an ordinary listing, where every row sits in the
    directory being listed. A search descends, so its results carry the sub-directory they
    were found in — without it two same-named results are indistinguishable.
    """
    document: VideoModel
    is_locked: bool
    relative_dir: str = ""


#: What one row of a directory listing can be.
BrowseEntry = DirectoryEntry | VideoEntry

#: Decides whether one video file met during a directory walk belongs in the result.
#: ``False`` excludes it; ``True`` and ``None`` keep it, so a caller with nothing to say
#: about an entry does not have to say it.
SearchOperator = Callable[[BaseFileEntry], bool | None]

#: Characters that would make a new directory name address something other than a single
#: child of the directory the user is looking at.
_NAME_SEPARATORS = ("/", "\\")


def _keyword(value: str | None) -> str | None:
    """A keyword that actually narrows anything, or None."""
    cleaned = (value or "").strip()
    return cleaned or None


@dataclass(slots=True)
class DirectorySearchCriteria:
    """
    What a search inside one directory is asking for.

    A blank field is not a filter: the panel sends all three fields every time, and an
    untouched box must not narrow the result set.

    ``name`` and ``author`` arrive as regexes whose metacharacters are already escaped by
    ``SearchKeywordModel`` — the same contract ``CatalogService.search_videos`` works
    under, so the two search surfaces cannot drift apart on what a dot means.
    """
    name: str | None = None
    author: str | None = None
    tags: list[str] = field(default_factory=list)

    def is_blank(self) -> bool:
        """True when nothing here would narrow anything."""
        return not (_keyword(self.name) or _keyword(self.author) or self.tags)


class BrowseFileService:
    def __init__(
        self,
        settings: Settings,
        dir_metadata_service: DirMetadataService,
        resource_handler_service: ResourceHandlerService,
        ffmpegService: FFmpegService,
        path_locks: PathLockRegistry,
    ):
        self.settings = settings
        self.dirMetadataService = dir_metadata_service
        self.resourceHandlerService = resource_handler_service
        self.ffmpegService = ffmpegService
        self.pathLocks = path_locks

    async def get_node_list_in_directory(self,
                                         abs_path: AbsolutePath,
                                         skipCache: bool = False,
                                         recursiveCalculation: bool = True
                                         ) -> list[BrowseEntry]:
        """
        Get a list of entries representing the files and directories under the specified absolute path.
        
        :param abs_path: The absolute path for which to retrieve the file and directory nodes.
        :type abs_path: AbsolutePath
        :param skipCache: Whether to skip cache when calculating directory metadata. Default is False.
        :type skipCache: bool
        :param recursiveCalculation: Whether to calculate directory metadata recursively. Default is True.
        :type recursiveCalculation: bool
        :return: A list of entries representing the files and directories under the specified absolute path.
        :rtype: list[BrowseEntry]
        """
        entries_out: list[BrowseEntry] = []
        try:
            if abs_path.is_root_level():
                for category in self.resourceHandlerService.get_all_categories():
                    entries_out.append(
                        DirectoryEntry(name=category, size=0.0, last_modify_time=0.0)
                    )
            elif abs_path.is_category_level():
                category = abs_path.category
                pseudo_names = self.resourceHandlerService.get_pseudo_names(category)
                for name in pseudo_names:
                    entry_node = await self._get_directory_node(
                        AbsolutePath.from_relative_path(
                            parsedPath=(category, name, None),
                            handlerService=self.resourceHandlerService,
                            settings=self.settings
                        ),
                        name,
                        skipCache,
                        recursiveCalculation,
                        list_when_empty=True
                    )
                    if entry_node is not None:
                        entries_out.append(entry_node)
            else:
                entries_out = await self._list_directory_level(
                    abs_path, skipCache, recursiveCalculation
                )

        except (OSError, Exception) as e:
            logger.exception(f"Error accessing directory {abs_path}: {e}")
            raise FileBrowseError(f"Error accessing directory {abs_path}")

        return entries_out

    async def _list_directory_level(self,
                                    abs_path: AbsolutePath,
                                    skipCache: bool,
                                    recursiveCalculation: bool) -> list[BrowseEntry]:
        """
        List a concrete directory: its sub-directories plus every video file it holds.

        Sub-directories need no database work and are resolved during the walk. Video
        files only get collected, then resolved as a single batch, so a directory holding
        a hundred videos costs a handful of round-trips instead of a few hundred — see
        ``_sync_video_documents``. Directories therefore lead the returned list; the
        frontend sorts the whole listing itself, so the grouping is not user-visible.

        :param abs_path: The absolute path of the directory to list.
        :type abs_path: AbsolutePath
        :param skipCache: Whether to skip cache when calculating directory metadata.
        :type skipCache: bool
        :param recursiveCalculation: Whether to calculate directory metadata recursively.
        :type recursiveCalculation: bool
        :return: The nodes of the directory: sub-directories first, then video files.
        :rtype: list[BrowseEntry]
        """
        category = abs_path.category
        handler = self.resourceHandlerService.get_handler(category)

        directory_entries: list[BrowseEntry] = []
        pending: list[_PendingVideo] = []

        with handler.list_directory(abs_path.FS_format_path()) as entries:
            for entry in entries:
                try:
                    entry_path = AbsolutePath.from_existing_path(
                        path=entry.path,
                        category=category,
                        handler=handler
                    )
                    if entry.is_dir():
                        entry_node = await self._get_directory_node(
                            entry_path, entry.name, skipCache, recursiveCalculation
                        )
                        if entry_node is not None:
                            directory_entries.append(entry_node)
                    elif entry.is_file() and handler.is_video_file(entry.name):
                        stat = entry.stat()
                        pending.append(
                            _PendingVideo(
                                db_path=entry_path.DB_format_path(),
                                fs_path=entry.path,
                                name=handler.get_filename_without_extension(entry.name),
                                mtime=stat.mtime,
                                size=stat.size
                            )
                        )
                except OSError as e:
                    logger.exception(f"Error processing file {entry.path}: {e}")
                    continue

        if not pending:
            return directory_entries

        # Files held by unfinished background work are disabled in the browser: one lookup
        # for all of them. Resolved before the sync because it also decides which files get
        # a document at all — see ``_sync_video_documents``.
        locked_paths = await self.pathLocks.locked_paths(item.db_path for item in pending)

        documents, has_new_file = await self._sync_video_documents(
            handler, category, pending, locked_paths
        )
        video_entries = [
            VideoEntry(document=document, is_locked=item.db_path in locked_paths)
            for item in pending
            if (document := documents.get(item.db_path)) is not None
        ]

        if has_new_file:
            await self.dirMetadataService.update_directory_metadata_forward(abs_path)

        return directory_entries + video_entries

    async def _sync_video_documents(self,
                                    handler: BaseResourceHandler,
                                    category: str,
                                    pending: list[_PendingVideo],
                                    locked_paths: set[str]) -> tuple[dict[str, VideoModel], bool]:
        """
        Resolve the database document of every video file found in one directory,
        inserting the ones that are new and filling in the durations that are missing.

        The whole directory costs one ``find``, at most one ``bulk_write``, and — only
        when new files were discovered — one further ``find`` to read the inserted
        documents back. ffprobe is the expensive part of this method, so it runs only
        for documents that actually lack a duration; those probes run concurrently and
        FFmpegService's own semaphore caps how many really overlap.

        A file that is locked but has no document is a migration writing into this
        directory: the bytes have started arriving, but the catalog record is still at
        the source and ``_execute_db_update`` is going to move it onto this very path.
        Inserting for it here would claim that path first and make the migration fail on
        the unique index. Such a file is not a video yet, so it gets no document — and,
        having none, drops out of the listing too. Once UPDATING_DB has run the record
        *is* at this path, the lookup below finds it, and the file lists normally
        (flagged locked, since its task is still active).

        Locked-with-a-document is the opposite case and stays untouched: that is the
        migration's source, which must keep listing so the browser can show it leaving.

        :param handler: The resource handler owning the directory being listed.
        :type handler: BaseResourceHandler
        :param category: The category the directory belongs to.
        :type category: str
        :param pending: The video files found while walking the directory.
        :type pending: list[_PendingVideo]
        :param locked_paths: DB paths held by unfinished background work, as reported by
            the path-lock registry. Migration is the case that motivated the rule above.
        :type locked_paths: set[str]
        :return: The document of each video keyed by DB path, and whether any file was new.
        :rtype: tuple[dict[str, VideoModel], bool]
        """
        documents = {
            document.path: document
            for document in await VideoModel.find(
                {"path": {"$in": [item.db_path for item in pending]}}
            ).to_list()
        }

        pending = [
            item for item in pending
            if item.db_path in documents or item.db_path not in locked_paths
        ]
        if not pending:
            return documents, False

        # Newly discovered files, plus known ones whose duration was never resolved.
        needs_duration = [
            item for item in pending
            if not (document := documents.get(item.db_path)) or not document.duration
        ]
        durations = dict(
            zip(
                (item.db_path for item in needs_duration),
                await asyncio.gather(*(
                    self.ffmpegService.get_video_duration(handler=handler, fs_path=item.fs_path)
                    for item in needs_duration
                ))
            )
        )

        operations: list[UpdateOne] = []
        inserted_paths: list[str] = []
        for item in pending:
            document = documents.get(item.db_path)
            if document is None:
                inserted_paths.append(item.db_path)
                new_document = VideoModel(
                    category=category,
                    path=item.db_path,
                    name=item.name,
                    isDir=False,
                    lastModifyTime=item.mtime,
                    size=item.size,
                    tags=[],
                    duration=durations.get(item.db_path, 0.0)
                )
                operations.append(
                    UpdateOne(
                        {"path": item.db_path},
                        {"$setOnInsert": new_document.model_dump(by_alias=True, exclude={"id"})},
                        upsert=True
                    )
                )
            elif item.db_path in durations:
                document.duration = durations[item.db_path]
                operations.append(
                    UpdateOne({"_id": document.id}, {"$set": {"duration": document.duration}})
                )

        if operations:
            await VideoModel.get_pymongo_collection().bulk_write(operations, ordered=False)

        if inserted_paths:
            # Read back instead of trusting the locally built model
            for document in await VideoModel.find({"path": {"$in": inserted_paths}}).to_list():
                documents[document.path] = document

        return documents, bool(inserted_paths)

    async def _get_directory_node(self,
                                  path: AbsolutePath,
                                  name: str,
                                  skipCache: bool,
                                  recursiveCalculation: bool,
                                  list_when_empty: bool = False) -> DirectoryEntry | None:
        """
        Helper method to build a directory entry from its calculated metadata.

        :param path: The absolute path of the directory.
        :type path: AbsolutePath
        :param name: The name of the directory.
        :type name: str
        :param skipCache: Whether to skip cache when calculating directory metadata.
        :type skipCache: bool
        :param recursiveCalculation: Whether to calculate directory metadata recursively.
        :type recursiveCalculation: bool
        :param list_when_empty: Whether this row exists for a reason other than what it
            holds. Set for configured pseudo-names, whose place in the listing comes from
            the configuration rather than from anything found on the storage.
        :type list_when_empty: bool
        :return: The node for the directory, or None if it holds nothing worth showing.
        :rtype: DirectoryEntry | None
        """
        total_size, last_modified_time = await self.dirMetadataService.calculate_directory_metadata(
            directory_path=path,
            skipCache=skipCache,
            recursiveCalculation=recursiveCalculation
        )
        if total_size == 0.0 or last_modified_time == 0.0:
            if not list_when_empty and not await self.dirMetadataService.is_user_created(
                path.category, path.DB_format_path()
            ):
                return None
        return DirectoryEntry(
            name=name, size=total_size, last_modify_time=last_modified_time
        )

    async def create_directory(self, parent_path: AbsolutePath, name: str) -> str:
        """
        Create a sub-directory under ``parent_path`` and record that a user made it.

        The record is what keeps the new folder listed: it holds no video yet, so it
        aggregates to zero, and ``_get_directory_node`` hides zero-aggregate directories.

        :param parent_path: The directory to create it in. Must be a real directory —
            the root and category levels list categories and configured mount points,
            neither of which is a place on the storage.
        :type parent_path: AbsolutePath
        :param name: The new directory's name, a single path segment.
        :type name: str
        :return: The DB-format path of the created directory.
        :rtype: str
        :raises InputValidationError: If the parent is not a real directory, the name is
            not a single usable segment, or something already occupies that name.
        """
        if parent_path.is_root_level() or parent_path.is_category_level():
            raise InputValidationError(
                field="parentPath",
                issue="a folder can only be created inside a resource directory",
            )

        cleaned = (name or "").strip()
        if not cleaned:
            raise InputValidationError(field="name", issue="folder name must not be blank")
        if any(separator in cleaned for separator in _NAME_SEPARATORS):
            raise InputValidationError(
                field="name", issue="folder name must not contain a path separator"
            )
        if cleaned in (".", ".."):
            raise InputValidationError(field="name", issue=f"'{cleaned}' is not a folder name")

        category = parent_path.category
        handler = self.resourceHandlerService.get_handler(category)
        new_fs_path = handler.join_path(parent_path.FS_format_path(), cleaned)

        try:
            handler.create_directory(new_fs_path)
        except FileExistsError:
            raise InputValidationError(
                field="name", issue=f"'{cleaned}' already exists in this directory"
            )
        except (OSError, Exception) as e:
            logger.exception(f"Error creating directory {new_fs_path}: {e}")
            raise FileBrowseError(f"Error creating directory {cleaned}")

        db_path = AbsolutePath.from_existing_path(
            path=new_fs_path, category=category, handler=handler
        ).DB_format_path()
        await self.dirMetadataService.mark_user_created(category, db_path)
        return db_path

    def get_all_video_entries_in_directory(self,
                                           mounted_directory_path: str,
                                           category: str,
                                           search_operator: SearchOperator | None = None
                                           ) -> list[BaseFileEntry]:
        """
        Get all video file entries under the given directory and its subdirectories.

        ``search_operator`` decides which of them are wanted. A rejected entry is dropped
        from the result and nothing else: the walk carries on, so a directory whose own
        files all fail the test still contributes whatever its sub-directories hold.

        :param mounted_directory_path: The path of the mounted directory.
        :type mounted_directory_path: str
        :param category: The category of the video files.
        :type category: str
        :param search_operator: Consulted for every video file met. Returning ``False``
            excludes that file; ``True``, ``None``, or no operator at all keeps it.
        :type search_operator: SearchOperator | None
        :return: A list of video file entries.
        :rtype: list[BaseFileEntry]
        """
        video_entries: list[BaseFileEntry] = []
        handler = self.resourceHandlerService.get_handler(category)
        try:
            with handler.list_directory(mounted_directory_path) as entries:
                for entry in entries:
                    if entry.is_file() and handler.is_video_file(entry.name):
                        if search_operator is None or search_operator(entry) is not False:
                            video_entries.append(entry)
                    elif entry.is_dir():
                        video_entries.extend(
                            self.get_all_video_entries_in_directory(
                                handler.get_path_standard_format(entry.path),
                                category,
                                search_operator
                            )
                        )
        except (OSError, Exception):
            logger.exception(f"Error accessing directory {mounted_directory_path} to get video entries.")
        return video_entries

    async def search_videos_in_directory(self,
                                         abs_path: AbsolutePath,
                                         criteria: DirectorySearchCriteria
                                         ) -> list[VideoEntry]:
        """
        Find the catalogued videos under ``abs_path`` that match ``criteria``.

        Two sources answer two different questions. The catalogue says *which videos
        match*: name, author and tags are metadata, and the name a user searches is the
        one they edited, not the one on disk. The storage says *which files are there*: a
        record whose file has since been removed must not be offered as something to play,
        edit or migrate. So the query narrows, and the walk confirms.

        Only videos that already have a document can match, and none is created here.
        A file the catalogue has never seen has no author and no tags to match against,
        and inserting for it would make a read operation quietly extend the catalogue —
        that is browsing's job, on the directory the user actually opened.

        :param abs_path: The directory to search, together with everything below it.
        :type abs_path: AbsolutePath
        :param criteria: The fields to match. Blank fields are not filters.
        :type criteria: DirectorySearchCriteria
        :return: The matching videos, each carrying its lock state and the sub-directory
            it was found in.
        :rtype: list[VideoEntry]
        :raises InputValidationError: If the path is not a real directory, or nothing in
            the criteria would narrow anything.
        :raises DatabaseOperationError: If the catalogue query itself fails.
        """
        if abs_path.is_root_level() or abs_path.is_category_level():
            raise InputValidationError(
                field="path",
                issue="a search runs inside a resource directory",
            )
        if criteria.is_blank():
            raise InputValidationError(
                field="criteria",
                issue="a search needs a name, an author or at least one tag",
            )

        category = abs_path.category
        handler = self.resourceHandlerService.get_handler(category)
        root_db_path = abs_path.DB_format_path()

        query_filters: dict = {"path": {"$regex": f"^{re.escape(root_db_path)}/"}}
        if name := _keyword(criteria.name):
            query_filters["name"] = {"$regex": name, "$options": "i"}
        if author := _keyword(criteria.author):
            query_filters["author"] = {"$regex": author, "$options": "i"}
        if criteria.tags:
            query_filters["tags"] = {"$all": list(criteria.tags)}

        try:
            candidates = {
                document.path: document
                for document in await VideoModel.find(query_filters).to_list()
            }
        except Exception as e:
            logger.exception(f"Database operation error during directory search: {e}")
            raise DatabaseOperationError(
                operation="search in directory", details=f"Filters-{query_filters}"
            )

        if not candidates:
            return []

        # Filled as the walk runs, so the path of a kept entry is converted once rather
        # than again on the way out.
        db_path_by_entry: dict[str, str] = {}

        def is_candidate(entry: BaseFileEntry) -> bool:
            db_path = AbsolutePath.from_existing_path(
                path=entry.path, category=category, handler=handler
            ).DB_format_path()
            if db_path not in candidates:
                return False
            db_path_by_entry[entry.path] = db_path
            return True

        documents = [
            candidates[db_path_by_entry[entry.path]]
            for entry in self.get_all_video_entries_in_directory(
                abs_path.FS_format_path(), category, search_operator=is_candidate
            )
        ]

        locked_paths = await self.pathLocks.locked_paths(
            document.path for document in documents
        )
        prefix_length = len(root_db_path) + 1
        return [
            VideoEntry(
                document=document,
                is_locked=document.path in locked_paths,
                relative_dir=posixpath.dirname(document.path[prefix_length:]),
            )
            for document in documents
        ]