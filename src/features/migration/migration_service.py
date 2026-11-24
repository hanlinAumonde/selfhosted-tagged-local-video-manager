import asyncio
from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass
import time
from typing import AsyncGenerator

import pymongo
from beanie.operators import In, Set
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from src.platform.jobs.progress import ProgressFrame
from src.platform.jobs.state_machine import TaskStateMachine
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.features.migration.device_slots import DeviceSlots
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.features.migration.migration_task import MigrationTaskModel
from src.platform.jobs.task_model import TaskStatus
from src.features.catalog.series_service import SeriesService
from src.features.catalog.video import VideoModel
from src.errors import _MigrationCancelled, InputValidationError
from src.logger import get_logger
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.base_resource_handler import BaseResourceHandler

logger = get_logger("migration_service")

_ACTIVE_STATUSES = [s.value for s in TaskStatus if s not in TaskStateMachine.TERMINAL_STATUSES]


@dataclass
class MigrationPreflightResult:
    valid: bool
    source_file_size: int
    conflict_exists: bool
    space_available: int | None
    space_sufficient: bool | None
    already_migrating: bool
    same_location: bool
    error_message: str | None = None


@dataclass(frozen=True)
class _Destination:
    """Where a source file would land in a target directory, before any conflict handling."""

    file_size: int
    file_name: str
    target_fs_path: str
    target_db_path: str


@dataclass(frozen=True)
class _Route:
    """The storages and FS-format paths one task's phases work on."""

    source: BaseResourceHandler
    target: BaseResourceHandler
    source_fs_path: str
    target_fs_path: str
    #: Where phase 1 writes: the target itself, or a staging file for an overwrite that
    #: the storage cannot do atomically.
    write_fs: str
    #: An overwrite whose finished write already is the replacement, so there is no
    #: partial copy of ours to discard.
    replaces_in_place: bool

    @property
    def same_storage(self) -> bool:
        # A path means nothing to another storage, so storage-side shortcuts (link, rename,
        # server-side copy) only apply within one handler: linking to an S3 key would
        # create a stray local file named after it.
        return self.source is self.target

    @property
    def may_skip_copy(self) -> bool:
        """Whether a link or a rename is worth attempting."""
        return self.same_storage and self.source.moves_without_copying


class MigrationService(TaskStateMachine[MigrationTaskModel]):

    task_model = MigrationTaskModel

    def __init__(
        self,
        resource_handler_service: ResourceHandlerService,
        dir_metadata_service: DirMetadataService,
        series_service: SeriesService,
        progress_flush_interval: float = 3.0,
        copy_slots: DeviceSlots | None = None,
    ):
        """
        :param copy_slots: Limits concurrent copies in total and per device. Only the
            worker that runs migrations needs it; the web process, which only creates,
            lists and cancels them, leaves it out.
        :type copy_slots: DeviceSlots | None
        """
        super().__init__(progress_flush_interval=progress_flush_interval)
        self.resourceHandlerService = resource_handler_service
        self.dirMetadataService = dir_metadata_service
        self.seriesService = series_service
        self.copy_slots = copy_slots

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def preflight(
        self,
        source_path: AbsolutePath,
        target_dir_path: AbsolutePath,
    ) -> MigrationPreflightResult:
        """
        Check whether a file could be migrated, without changing anything.

        Runs five checks — source exists, target space, name conflict, an already-active
        task, and source-equals-target. A missing source short-circuits the rest, since
        every remaining check would be meaningless.

        :param source_path: The video file to move.
        :type source_path: AbsolutePath
        :param target_dir_path: The directory to move it into.
        :type target_dir_path: AbsolutePath
        :return: The findings, with ``valid`` summarising whether creation may proceed.
        :rtype: MigrationPreflightResult
        """
        destination = await self._locate(source_path, target_dir_path)
        if destination is None:
            return MigrationPreflightResult(
                valid=False,
                source_file_size=0,
                conflict_exists=False,
                space_available=None,
                space_sufficient=None,
                already_migrating=False,
                same_location=False,
                error_message="source file does not exist",
            )

        target_handler = target_dir_path.handler
        source_db = source_path.DB_format_path()
        same_location = source_db == destination.target_db_path
        conflict_exists = (
            not same_location and await target_handler.stat(destination.target_fs_path) is not None
        )
        already_migrating = await self._is_actively_migrating(source_db)
        space_available = await target_handler.get_available_space(target_dir_path.FS_format_path())
        space_sufficient = None if space_available is None else space_available >= destination.file_size

        errors = [
            message
            for failed, message in (
                (same_location, "source path and target path are the same"),
                (already_migrating, "the file already has an active migration task"),
                (space_sufficient is False, "insufficient space available at the target location"),
            )
            if failed
        ]
        return MigrationPreflightResult(
            valid=not errors,
            source_file_size=destination.file_size,
            conflict_exists=conflict_exists,
            space_available=space_available,
            space_sufficient=space_sufficient,
            already_migrating=already_migrating,
            same_location=same_location,
            error_message=";".join(errors) or None,
        )

    async def create_task(
        self,
        source_path: AbsolutePath,
        target_dir_path: AbsolutePath,
        conflict_strategy: str | None,
        batch_id: ObjectId | None = None,
    ) -> MigrationTaskModel:
        """
        Persist a PENDING migration task, resolving any name conflict up front.

        Only creates the record — dispatch it to the migration queue to actually run it. The
        conflict strategy is applied here rather than at execution time so the final
        target path is fixed and visible before any bytes move.

        Duplicate prevention is enforced by a partial unique index covering only
        non-terminal statuses, so a file may be migrated again once an earlier task has
        settled.

        :param source_path: The video file to move.
        :type source_path: AbsolutePath
        :param target_dir_path: The directory to move it into.
        :type target_dir_path: AbsolutePath
        :param conflict_strategy: ``"overwrite"``, ``"rename"``, ``"skip"``, or None when
            the caller believes there is no conflict. Only consulted if the target name is
            actually taken.
        :type conflict_strategy: str | None
        :param batch_id: The batch this task is a child of, if any.
        :type batch_id: ObjectId | None
        :return: The inserted task, in PENDING status.
        :rtype: MigrationTaskModel
        :raises InputValidationError: If the source is gone, the strategy is ``"skip"`` or
            missing while a conflict exists, or the file already has an active task.
        """
        destination = await self._locate(source_path, target_dir_path)
        if destination is None:
            raise InputValidationError(field="source_path", issue="source file does not exist")

        target_handler = target_dir_path.handler
        renamed_target_path: str | None = None
        if await target_handler.stat(destination.target_fs_path) is not None:
            if conflict_strategy == "rename":
                renamed_fs_path = await self._generate_unique_name(
                    target_handler, target_dir_path.FS_format_path(), destination.file_name
                )
                renamed_target_path = target_handler.convert_to_DB_format_path(renamed_fs_path)
            elif conflict_strategy == "skip":
                raise InputValidationError(field="conflict_strategy", issue="user chose to skip, task not created")
            elif conflict_strategy != "overwrite":
                raise InputValidationError(field="conflict_strategy", issue="target exists with same name but no conflict strategy specified")

        now = time.time()
        task = MigrationTaskModel(
            source_path=source_path.DB_format_path(),
            source_category=source_path.category,
            target_path=renamed_target_path or destination.target_db_path,
            target_category=target_dir_path.category,
            file_name=source_path.handler.get_filename_without_extension(destination.file_name),
            file_size=destination.file_size,
            status=TaskStatus.PENDING,
            conflict_strategy=conflict_strategy,
            renamed_target_path=renamed_target_path,
            batch_id=batch_id,
            created_at=now,
            updated_at=now,
        )

        try:
            await task.insert()
        except DuplicateKeyError:
            raise InputValidationError(
                field="source_path",
                issue="the file already has an active migration task, cannot create duplicate",
            )

        logger.info(f"Migration task created: {task.id} | {task.source_path} -> {task.target_path}")
        return task

    async def cancel_task(self, task_id: str) -> MigrationTaskModel:
        """
        Ask a task to stop.

        Runs in the web process, which shares no memory with the worker, so both outcomes
        are a single conditional write to the task document:

        * PENDING and due to start with the copy — settled as CANCELLED on the spot. The
          worker's claim then misses, so the task never starts, even if its message is
          already on the queue.
        * PENDING but resuming past the copy — refused like any later phase. Recovery or
          a retry requeued it with the first phase done, and nothing here could undo that.
        * PROCESSING — ``cancel_requested`` is raised. The worker reads it back on its next
          progress flush and unwinds the copy, cleaning up as it goes.

        The two writes are tried in that order, so a task the worker claims in between
        still ends up flagged.

        :param task_id: String form of the task's ObjectId.
        :type task_id: str
        :return: The task document. For a PROCESSING task the status still reads
            PROCESSING — cancellation completes asynchronously.
        :rtype: MigrationTaskModel
        :raises InputValidationError: If the task does not exist, or is past the copy.
        """
        oid = ObjectId(task_id)
        now = time.time()

        settled = await MigrationTaskModel.find_one(
            MigrationTaskModel.id == oid,
            MigrationTaskModel.status == TaskStatus.PENDING,
            In(MigrationTaskModel.resume_from, [None, TaskStatus.PROCESSING]),
        ).update(Set({
            MigrationTaskModel.status: TaskStatus.CANCELLED,
            MigrationTaskModel.updated_at: now,
            MigrationTaskModel.completed_at: now,
        }))
        if not settled.matched_count:
            flagged = await MigrationTaskModel.find_one(
                MigrationTaskModel.id == oid, MigrationTaskModel.status == TaskStatus.PROCESSING
            ).update(Set({MigrationTaskModel.cancel_requested: True}))
            if not flagged.matched_count:
                task = await MigrationTaskModel.get(oid)
                if task is None:
                    raise InputValidationError(field="task_id", issue="task does not exist")
                phase = task.resume_from if task.status == TaskStatus.PENDING else task.status
                raise InputValidationError(field="task_id", issue=f"current status does not allow cancellation: {phase}")

        return await MigrationTaskModel.get(oid)

    async def prepare_retry(self, task_id: str) -> TaskStatus:
        """
        Validate a retry request and reset the task so it can be queued again.

        Clears the previous failure and stores the task back as PENDING with the phase to
        resume at in ``resume_from``, derived from the recorded ``failed_step``. Nothing is
        executed here — the caller dispatches the task, and the worker reads the resume
        point off the document when it claims it.

        When the resume point is PROCESSING, any partial file from the failed attempt is
        removed and the byte counter zeroed first, so the copy restarts clean.

        :param task_id: String form of the task's ObjectId.
        :type task_id: str
        :return: The phase the task will resume at. Falls back to PROCESSING if
            ``failed_step`` is absent or unparsable.
        :rtype: TaskStatus
        :raises InputValidationError: If the task does not exist or is not FAILED.
        """
        task = await MigrationTaskModel.get(ObjectId(task_id))
        if task is None:
            raise InputValidationError(field="task_id", issue="task does not exist")
        if task.status != TaskStatus.FAILED:
            raise InputValidationError(field="task_id", issue=f"only failed tasks can be retried, current status: {task.status}")

        start_from = TaskStatus.PROCESSING
        if task.failed_step:
            try:
                start_from = TaskStateMachine._RESUME_POINT_BY_STATUS.get(
                    TaskStatus(task.failed_step), TaskStatus.PROCESSING
                )
            except ValueError:
                logger.warning(f"Task {task_id} has unparsable failed_step '{task.failed_step}', restarting from copy")

        # Same rewind a crash recovery does, so a retry and a restart leave the task in
        # exactly the same state before it is queued again.
        before = self._dump(task)
        await self._compensate_before_resume(task, start_from)

        await task.set({
            **self._changed_fields(before, task),
            MigrationTaskModel.status: TaskStatus.PENDING,
            MigrationTaskModel.resume_from: start_from,
            MigrationTaskModel.cancel_requested: False,
            MigrationTaskModel.error_message: None,
            MigrationTaskModel.failed_step: None,
            MigrationTaskModel.completed_at: None,
            MigrationTaskModel.updated_at: time.time(),
        })
        return start_from

    async def list_tasks(
        self,
        status_filter: list[str] | None,
        page: int,
        page_size: int,
        batch_id: str | None = None,
    ) -> tuple[list[MigrationTaskModel], int]:
        """
        Fetch a page of migration tasks, newest first.

        :param status_filter: Statuses to include, or None for all of them.
        :type status_filter: list[str] | None
        :param page: 1-based page number.
        :type page: int
        :param page_size: Rows per page.
        :type page_size: int
        :param batch_id: Only the children of this batch, or None for every task.
        :type batch_id: str | None
        :return: The page of tasks, and how many match the filter in total.
        :rtype: tuple[list[MigrationTaskModel], int]
        """
        query_filter: dict = {}
        if status_filter:
            query_filter["status"] = {"$in": status_filter}
        if batch_id:
            query_filter["batch_id"] = ObjectId(batch_id)

        total_count = await MigrationTaskModel.find(query_filter).count()
        tasks = (
            await MigrationTaskModel.find(query_filter)
                .sort([("created_at", pymongo.DESCENDING)])
                .skip((page - 1) * page_size)
                .limit(page_size)
                .to_list()
        )
        return tasks, total_count

    async def locked_paths(self, db_paths: Iterable[str]) -> set[str]:
        """
        Report which of the given paths this feature is holding.

        Implements ``PathLockProvider``, which is how readers such as the catalogue and the
        directory browser learn that a file is spoken for without importing this feature.

        :param db_paths: Paths in DB format. Empty or falsy entries are ignored.
        :type db_paths: Iterable[str]
        :return: The subset of the input held by a task that has not settled.
        :rtype: set[str]
        """
        wanted = {path for path in db_paths if path}
        if not wanted:
            return set()

        path_list = list(wanted)
        tasks = await MigrationTaskModel.find(
            {
                "status": {"$in": _ACTIVE_STATUSES},
                "$or": [
                    {"source_path": {"$in": path_list}},
                    {"target_path": {"$in": path_list}},
                    {"renamed_target_path": {"$in": path_list}},
                ],
            }
        ).to_list()

        # A matched task may reference paths outside the requested set, so intersect rather
        # than taking every path it mentions.
        return {
            path
            for task in tasks
            for path in (task.source_path, task.target_path, task.renamed_target_path)
            if path in wanted
        }

    async def is_file_locked(self, db_path: str) -> bool:
        """
        Check whether a path is tied up by a migration that has not settled.

        Matches the path as source, target or renamed target: a file on its way out and a
        file about to be overwritten both need protecting. Mutation resolvers call this to
        reject edits and deletes on files that are mid-migration.

        :param db_path: Path in DB format.
        :type db_path: str
        :return: True if any non-terminal task references this path.
        :rtype: bool
        """
        return db_path in await self.locked_paths([db_path])

    async def refresh_directory_metadata(self, tasks: Iterable[MigrationTaskModel]) -> None:
        """
        Recompute the aggregates of every directory these migrations moved a file out of
        or into, each directory once.

        Best effort: a failure is logged per directory, since the files have already moved.

        :param tasks: Migrations that have put their file at the target.
        :type tasks: Iterable[MigrationTaskModel]
        :rtype: None
        """
        directories: dict[tuple[str, str], None] = {}
        for task in tasks:
            directories[(task.source_category, task.source_path.rsplit("/", 1)[0])] = None
            directories[(task.target_category, task.final_target_path.rsplit("/", 1)[0])] = None

        for category, dir_db in directories:
            try:
                handler = self.resourceHandlerService.get_handler(category)
                directory = AbsolutePath.from_existing_path(dir_db, category, handler)
                await self.dirMetadataService.update_directory_metadata_forward(directory)
            except Exception as e:
                logger.warning(f"Directory metadata update failed for {dir_db}: {e}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _locate(
        self, source_path: AbsolutePath, target_dir_path: AbsolutePath
    ) -> _Destination | None:
        """Where the source would land under its own name; None if the source is gone."""
        source_fs_path = source_path.FS_format_path()
        source_info = await source_path.handler.stat(source_fs_path)
        if source_info is None:
            return None

        target_handler = target_dir_path.handler
        file_name = source_fs_path.rsplit("/", 1)[-1]
        target_fs_path = target_handler.join_path(target_dir_path.FS_format_path(), file_name)
        return _Destination(
            file_size=int(source_info.size),
            file_name=file_name,
            target_fs_path=target_fs_path,
            target_db_path=target_handler.convert_to_DB_format_path(target_fs_path),
        )

    async def _is_actively_migrating(self, db_path: str) -> bool:
        # Narrower than ``is_file_locked``, which also covers targets: this one answers
        # "is this file already on its way out?".
        query = {"status": {"$in": _ACTIVE_STATUSES}, "source_path": db_path}
        return await MigrationTaskModel.find(query).count() > 0

    def _route(self, task: MigrationTaskModel) -> _Route:
        source = self.resourceHandlerService.get_handler(task.source_category)
        target = self.resourceHandlerService.get_handler(task.target_category)
        target_fs_path = target.convert_to_FS_format_path(task.final_target_path)

        overwrite = task.conflict_strategy == "overwrite"
        if overwrite and not target.writes_atomically:
            # What sits at the target belongs to another video until the migration can no
            # longer stop, so the copy is staged beside it. The name leaves out the file's
            # own so it cannot exceed the filesystem's limit, and ``.part`` keeps it out of
            # directory listings.
            write_fs = target.join_path(target.dirname(target_fs_path), f".migrating-{task.id}.part")
        else:
            write_fs = target_fs_path

        return _Route(
            source=source,
            target=target,
            source_fs_path=source.convert_to_FS_format_path(task.source_path),
            target_fs_path=target_fs_path,
            write_fs=write_fs,
            replaces_in_place=overwrite and target.writes_atomically,
        )

    def _copy_slots(self, task: MigrationTaskModel) -> AbstractAsyncContextManager:
        if self.copy_slots is None:
            return nullcontext()
        return self.copy_slots.hold(
            self.copy_slots.devices_of(task.source_path, task.final_target_path)
        )

    def _may_skip_slots(self, task: MigrationTaskModel) -> bool:
        # A link or a rename moves no bytes, yet the slot is taken before the claim, so it
        # would otherwise wait behind whichever long copy holds its device. Such a task
        # takes its slots later, only if it turns out to need a copy after all.
        if self.copy_slots is None or not self._route(task).may_skip_copy:
            return False
        source_device, target_device = self.copy_slots.devices_of(
            task.source_path, task.final_target_path
        )
        return source_device.name == target_device.name

    async def _discard_partial_copy(self, route: _Route) -> None:
        """Remove what the first phase wrote, and nothing else."""
        if not route.replaces_in_place:
            await self._cleanup_target(route.target, route.write_fs)

    @staticmethod
    async def _cleanup_target(handler: BaseResourceHandler, target_fs_path: str) -> None:
        """
        Delete a partially written target file, best effort.

        Never raises: this runs on paths that are already handling a cancellation, a
        failure or a crash recovery, where a cleanup problem must not mask the original
        cause.
        """
        try:
            if await handler.stat(target_fs_path) is not None:
                await handler.delete_file(target_fs_path)
        except Exception as e:
            logger.warning(f"Failed to cleanup target file {target_fs_path}: {e}")

    @staticmethod
    async def _generate_unique_name(handler: BaseResourceHandler, dir_fs: str, filename: str) -> str:
        """The first free ``name(n).ext`` in a directory, as a full FS-format path."""
        name_no_ext = handler.get_filename_without_extension(filename)
        ext = handler.get_file_extension(filename)
        suffix = f".{ext}" if ext else ""
        counter = 1
        while True:
            candidate = handler.join_path(dir_fs, f"{name_no_ext}({counter}){suffix}")
            if await handler.stat(candidate) is None:
                return candidate
            counter += 1

    # ------------------------------------------------------------------
    # Template hooks
    # ------------------------------------------------------------------

    def _processing_slot(self, task: MigrationTaskModel) -> AbstractAsyncContextManager:
        """Copy slots on the source's and the target's device, held while the file copies."""
        if self._may_skip_slots(task):
            return nullcontext()
        return self._copy_slots(task)

    async def _compensate_before_resume(
        self, task: MigrationTaskModel, start_from: TaskStatus
    ) -> None:
        """
        Remove the half-written target file left by a copy that died mid-flight.

        Only the copy phase leaves anything behind: the DB update and the source deletion
        are both idempotent and safe to replay as-is. Resetting the byte counter keeps the
        task list from showing progress the restarted copy has not made yet.
        """
        if start_from != TaskStatus.PROCESSING:
            return
        await self._discard_partial_copy(self._route(task))
        task.set_progress(0)

    # ------------------------------------------------------------------
    # Phase: PROCESSING
    # ------------------------------------------------------------------

    async def _execute_processing(
        self, task: MigrationTaskModel
    ) -> AsyncGenerator[ProgressFrame, None]:
        """
        Phase 1 — put the file at the target by hard link or copy, or settle on renaming it.

        The source keeps its name through this phase on every path, which is what makes
        everything written here safe to discard. A filesystem without hard links renames
        in phase 2 instead, once a cancel can no longer land.

        On success the task moves to PROCESS_DONE. On cancellation or failure the partial
        copy is removed, since this phase always restarts from the beginning. A copy
        failure is re-raised after that, so the state machine records it as FAILED.
        """
        route = self._route(task)

        await self._update_task_status(task, TaskStatus.PROCESSING)
        yield self._make_progress(task, message="Starting copy")

        linked = route.may_skip_copy and await route.source.link_file(route.source_fs_path, route.write_fs)
        renames = (
            route.may_skip_copy
            and not linked
            and await route.source.can_rename(route.source_fs_path, route.target_fs_path)
        )
        if not linked and not renames:
            slots = self._copy_slots(task) if self._may_skip_slots(task) else nullcontext()
            async with slots:
                async for frame in self._stream_copy(task, route):
                    yield frame
            if task.status == TaskStatus.CANCELLED:
                return

        if not await self._finish_processing(
            task, bytes_transferred=task.file_size, move_by_rename=renames
        ):
            if not route.replaces_in_place:
                yield await self._settle_cancelled(task, route, task.file_size)
                return
            # The replaced object went when the upload completed; a cancel can no longer
            # restore it, and stopping now would leave its record pointing at another file.
            await self._update_task_status(
                task, TaskStatus.PROCESS_DONE, bytes_transferred=task.file_size
            )

        yield self._make_progress(task, current=task.file_size, message="Copy completed")

    async def _settle_cancelled(
        self, task: MigrationTaskModel, route: _Route, current: int
    ) -> ProgressFrame:
        await self._discard_partial_copy(route)
        await self._update_task_status(task, TaskStatus.CANCELLED)
        self._cancel_requested.pop(str(task.id), None)
        return self._make_progress(task, current=current, message="cancelled")

    async def _stream_copy(
        self, task: MigrationTaskModel, route: _Route
    ) -> AsyncGenerator[ProgressFrame, None]:
        """
        Copy the file to ``route.write_fs``, reporting progress each second.

        ``write_file_streaming`` consumes its whole iterator inside a single await, which
        would keep this generator's frame suspended for the entire copy and make it unable
        to yield anything. Running the copy as its own Task is what allows progress to be
        reported while the transfer is in flight; ``counting_reader`` sits in between,
        tallying bytes and checking for cancellation on every chunk.

        Leaves the task CANCELLED if a cancel stopped the copy; any other failure is
        re-raised after the partial copy is cleaned up.
        """
        task_id = str(task.id)
        bytes_copied = 0

        async def counting_reader():
            nonlocal bytes_copied
            async for chunk in route.source.read_file_streaming(route.source_fs_path):
                if self._cancel_requested.get(task_id):
                    raise _MigrationCancelled()
                bytes_copied += len(chunk)
                yield chunk

        def report_copied(copied: int) -> None:
            """Does for a server-side copy what ``counting_reader`` does for a streamed one."""
            nonlocal bytes_copied
            if self._cancel_requested.get(task_id):
                raise _MigrationCancelled()
            bytes_copied = copied

        async def copy() -> None:
            if route.same_storage and await route.source.copy_server_side(
                route.source_fs_path, route.write_fs, report_copied
            ):
                return
            await route.target.write_file_streaming(route.write_fs, counting_reader())

        copy_task = asyncio.create_task(copy())

        try:
            while not copy_task.done():
                await asyncio.sleep(1)
                await self._maybe_flush_progress(task, bytes_copied)
                yield self._make_progress(task, current=bytes_copied)
        finally:
            # Never leave the copy running unattended: if this generator is closed or the
            # worker is cancelled, the copy must go down with it.
            if not copy_task.done():
                copy_task.cancel()

        try:
            await copy_task
        except _MigrationCancelled:
            yield await self._settle_cancelled(task, route, bytes_copied)
        except Exception:
            await self._discard_partial_copy(route)
            raise

    # ------------------------------------------------------------------
    # Phase: COMMITTING
    # ------------------------------------------------------------------

    async def _execute_commit(self, task: MigrationTaskModel) -> None:
        """
        Phase 2 — finish the move phase 1 left over, then repoint the video record.

        Written to be idempotent, because recovery and retry can both replay this phase
        after it already succeeded. If no record matches the source path, that is only
        accepted as "already done" when a record really does exist at the target;
        otherwise the record is genuinely missing and the task must fail.

        Under the ``"overwrite"`` strategy the record occupying the target path is deleted
        first — unless it is the very record being moved, which is what a replay looks like.
        """
        await self._update_task_status(task, TaskStatus.COMMITTING)
        await self._put_file_at_target(self._route(task), task.move_by_rename)

        target_path = task.final_target_path
        video = await VideoModel.find_one({"path": task.source_path})

        if video is None:
            # An interrupted or retried run may already have moved the record. Only treat
            # that as success if the target record really is there.
            if await VideoModel.find_one({"path": target_path}) is None:
                raise Exception(f"Source video record not found: {task.source_path}")
            logger.info(f"Task {task.id}: video record already at target, skipping DB update")
            await self._update_task_status(task, TaskStatus.COMMITTED)
            return

        if task.conflict_strategy == "overwrite":
            conflicting = await VideoModel.find_one({"path": target_path})
            if conflicting is not None and conflicting.id != video.id:
                await conflicting.delete()
                await self.seriesService.detach([str(conflicting.id)])

        video.path = target_path
        video.category = task.target_category
        await video.save()

        await self._update_task_status(task, TaskStatus.COMMITTED)

    @staticmethod
    async def _put_file_at_target(route: _Route, move_by_rename: bool) -> None:
        """
        Do the move the first phase left for this one: a rename, or publishing a staged copy.

        Belongs here and not at the end of phase 1: a cancel can only land on a PROCESSING
        task, so from here on the source's old place and the replaced file are no longer
        needed. A file already gone from where it would move from was moved by an earlier
        run of this phase.
        """
        if move_by_rename:
            if await route.source.stat(route.source_fs_path) is not None:
                await route.source.replace_file(route.source_fs_path, route.target_fs_path)
            elif await route.target.stat(route.target_fs_path) is None:
                raise Exception(f"File to migrate not found: {route.source_fs_path}")
            return

        if route.write_fs != route.target_fs_path and await route.target.stat(route.write_fs) is not None:
            await route.target.replace_file(route.write_fs, route.target_fs_path)

    # ------------------------------------------------------------------
    # Phase: CLEANING_UP
    # ------------------------------------------------------------------

    async def _execute_cleanup(self, task: MigrationTaskModel) -> str | None:
        """
        Phase 3 — delete the original and refresh both directories' metadata.

        Everything here is best effort. By this point the file has been copied and the
        database already points at the new location, so the migration has succeeded; a
        leftover source file or a stale directory aggregate is worth a warning, not a
        failure. The task therefore always ends COMPLETED, and only a failed source
        deletion is returned as a warning for the user.
        """
        route = self._route(task)
        await self._update_task_status(task, TaskStatus.CLEANING_UP)

        warning = None
        # Decided by the flag, not by the source's absence: after a rename, a file at the
        # old path is a new one that someone else put there.
        if not task.move_by_rename:
            try:
                await route.source.delete_file(route.source_fs_path)
            except Exception as e:
                warning = f"Source file deletion failed: {e}"
                logger.warning(f"Task {task.id}: {warning}")

        # A batch refreshes the directories of all its children once, after the last one.
        if task.batch_id is None:
            await self.refresh_directory_metadata([task])

        await self._update_task_status(task, TaskStatus.COMPLETED)
        return warning
