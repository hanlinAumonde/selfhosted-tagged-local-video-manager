import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
import time
from typing import AsyncGenerator

import pymongo
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from src.platform.jobs.progress import ProgressFrame
from src.platform.jobs.state_machine import TaskStateMachine
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.storage.resource_handler_service import ResourceHandlerService
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus
from src.features.catalog.video import VideoModel
from src.errors import _MigrationCancelled, InputValidationError
from src.logger import get_logger
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.base_resource_handler import BaseResourceHandler

logger = get_logger("migration_service")

#: Key this service is registered under in ``TaskRunner``, and the one callers pass to
#: submit or observe a migration. Shared so the string is written down exactly once.
MIGRATION_EXECUTOR_KEY = "migration"


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


class MigrationService(TaskStateMachine[MigrationTaskModel]):

    task_model = MigrationTaskModel

    def __init__(
        self,
        resource_handler_service: ResourceHandlerService,
        dir_metadata_service: DirMetadataService,
        progress_flush_interval: float = 3.0,
    ):
        super().__init__(progress_flush_interval=progress_flush_interval)
        self.resourceHandlerService = resource_handler_service
        self.dirMetadataService = dir_metadata_service

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve_paths(
        self, task: MigrationTaskModel
    ) -> tuple[BaseResourceHandler, BaseResourceHandler, str, str]:
        """
        Work out the two storage handlers and the two FS-format paths a task operates on.

        Migration is the task type that happens to have a source *and* a target; the
        template knows nothing about either, so each phase resolves what it needs here.

        :param task: The task being executed.
        :type task: MigrationTaskModel
        :return: ``(source_handler, target_handler, source_fs, target_fs)``, with the
            target already resolved for any rename.
        :rtype: tuple[BaseResourceHandler, BaseResourceHandler, str, str]
        """
        source_handler = self.resourceHandlerService.get_handler(task.source_category)
        target_handler = self.resourceHandlerService.get_handler(task.target_category)

        source_fs = source_handler.convert_to_FS_format_path(task.source_path)
        target_db = task.renamed_target_path or task.target_path
        target_fs = target_handler.convert_to_FS_format_path(target_db)

        return source_handler, target_handler, source_fs, target_fs

    async def _compensate_before_resume(
        self, task: MigrationTaskModel, start_from: TaskStatus
    ) -> None:
        """
        Remove the half-written target file left by a copy that died mid-flight.

        Only the copy phase leaves anything behind: the DB update and the source deletion
        are both idempotent and safe to replay as-is. Resetting the byte counter keeps the
        task list from showing progress the restarted copy has not made yet.

        :param task: The task about to be re-queued.
        :type task: MigrationTaskModel
        :param start_from: The phase it will resume at.
        :type start_from: TaskStatus
        :rtype: None
        """
        if start_from != TaskStatus.PROCESSING:
            return

        _, target_handler, _, target_fs = self._resolve_paths(task)
        self._cleanup_target(target_handler, target_fs)
        task.set_progress(0)

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
        source_handler = source_path.handler
        target_handler = target_dir_path.handler

        source_fs = source_path.FS_format_path()
        target_dir_fs = target_dir_path.FS_format_path()

        if not source_handler.file_exists(source_fs):
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

        file_size = int(source_handler.get_size(source_fs))
        filename = source_fs.rsplit("/", 1)[-1]

        target_file_fs = target_handler.join_path(target_dir_fs, filename)

        source_db = source_path.DB_format_path()
        target_db = target_handler.convert_to_DB_format_path(target_file_fs)
        same_location = source_db == target_db

        conflict_exists = target_handler.file_exists(target_file_fs) if not same_location else False

        already_migrating = await self._is_actively_migrating(source_db)

        space_available = target_handler.get_available_space(target_dir_fs)
        if space_available is not None:
            space_sufficient = space_available >= file_size
        else:
            space_sufficient = None

        errors: list[str] = []
        if same_location:
            errors.append("source path and target path are the same")
        if already_migrating:
            errors.append("the file already has an active migration task")
        if space_sufficient is False:
            errors.append("insufficient space available at the target location")

        valid = len(errors) == 0
        error_message = ";".join(errors) if errors else None

        return MigrationPreflightResult(
            valid=valid,
            source_file_size=file_size,
            conflict_exists=conflict_exists,
            space_available=space_available,
            space_sufficient=space_sufficient,
            already_migrating=already_migrating,
            same_location=same_location,
            error_message=error_message,
        )

    async def create_task(
        self,
        source_path: AbsolutePath,
        target_dir_path: AbsolutePath,
        conflict_strategy: str | None,
    ) -> MigrationTaskModel:
        """
        Persist a PENDING migration task, resolving any name conflict up front.

        Only creates the record — call ``TaskRunner.submit`` to actually run it. The
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
        :return: The inserted task, in PENDING status.
        :rtype: MigrationTaskModel
        :raises InputValidationError: If the source is gone, the strategy is ``"skip"`` or
            missing while a conflict exists, or the file already has an active task.
        """
        source_handler = source_path.handler
        target_handler = target_dir_path.handler

        source_fs = source_path.FS_format_path()
        target_dir_fs = target_dir_path.FS_format_path()

        if not source_handler.file_exists(source_fs):
            raise InputValidationError(field="source_path", issue="source file does not exist")

        file_size = int(source_handler.get_size(source_fs))
        filename = source_fs.rsplit("/", 1)[-1]
        file_name_no_ext = source_handler.get_filename_without_extension(filename)

        target_file_fs = target_handler.join_path(target_dir_fs, filename)
        target_db = target_handler.convert_to_DB_format_path(target_file_fs)

        renamed_target_path: str | None = None

        if target_handler.file_exists(target_file_fs):
            if conflict_strategy == "overwrite":
                pass
            elif conflict_strategy == "rename":
                target_file_fs = self._generate_unique_name(target_handler, target_dir_fs, filename)
                renamed_target_path = target_handler.convert_to_DB_format_path(target_file_fs)
            elif conflict_strategy == "skip":
                raise InputValidationError(field="conflict_strategy", issue="user chose to skip, task not created")
            else:
                raise InputValidationError(field="conflict_strategy", issue="target exists with same name but no conflict strategy specified")

        actual_target_db = renamed_target_path or target_db
        now = time.time()

        task = MigrationTaskModel(
            source_path=source_path.DB_format_path(),
            source_category=source_path.category,
            target_path=actual_target_db,
            target_category=target_dir_path.category,
            file_name=file_name_no_ext,
            file_size=file_size,
            status=TaskStatus.PENDING,
            conflict_strategy=conflict_strategy,
            renamed_target_path=renamed_target_path,
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

        A PENDING task is settled immediately, since nothing has happened yet; whichever
        worker later pops it from the queue sees the terminal status and skips it. A
        PROCESSING task can only be stopped cooperatively, so the flag is raised and the
        copy loop unwinds itself at the next chunk boundary, cleaning up as it goes.

        The flag is raised in both cases, to also cover the narrow window where a task has
        just left the queue but has not started copying yet.

        :param task_id: String form of the task's ObjectId.
        :type task_id: str
        :return: The task document. For a PROCESSING task the status still reads
            PROCESSING — cancellation completes asynchronously.
        :rtype: MigrationTaskModel
        :raises InputValidationError: If the task does not exist, or has already settled.
        """
        task = await MigrationTaskModel.get(ObjectId(task_id))
        if task is None:
            raise InputValidationError(field="task_id", issue="task does not exist")
        if task.status not in (TaskStatus.PENDING, TaskStatus.PROCESSING):
            raise InputValidationError(field="task_id", issue=f"current status does not allow cancellation: {task.status}")

        if task.status == TaskStatus.PENDING:
            await self._update_task_status(task, TaskStatus.CANCELLED)

        self.request_cancel(str(task.id))
        return task

    async def prepare_retry(self, task_id: str) -> TaskStatus:
        """
        Validate a retry request and reset the task so it can be queued again.

        Clears the previous failure, puts the task back to PENDING and returns the phase to
        resume at, derived from the recorded ``failed_step``. Nothing is executed here —
        the caller passes the returned phase to ``TaskRunner.submit``.

        When the resume point is PROCESSING, any partial file from the failed attempt is
        removed and the byte counter zeroed first, so the copy restarts clean.

        :param task_id: String form of the task's ObjectId.
        :type task_id: str
        :return: The phase the runner should resume from. Falls back to PROCESSING if
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
        await self._compensate_before_resume(task, start_from)

        task.status = TaskStatus.PENDING
        task.error_message = None
        task.failed_step = None
        task.completed_at = None
        task.updated_at = time.time()
        await task.save()

        return start_from

    async def list_tasks(
        self, status_filter: list[str] | None, page: int, page_size: int
    ) -> tuple[list[MigrationTaskModel], int]:
        """
        Fetch a page of migration tasks, newest first.

        :param status_filter: Statuses to include, or None for all of them.
        :type status_filter: list[str] | None
        :param page: 1-based page number.
        :type page: int
        :param page_size: Rows per page.
        :type page_size: int
        :return: The page of tasks, and how many match the filter in total.
        :rtype: tuple[list[MigrationTaskModel], int]
        """
        query_filter: dict = {}
        if status_filter:
            query_filter["status"] = {"$in": status_filter}

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
    
        active_statuses = [
            s.value for s in TaskStatus if s not in TaskStateMachine.TERMINAL_STATUSES
        ]
        path_list = list(wanted)
        tasks = await MigrationTaskModel.find(
            {
                "status": {"$in": active_statuses},
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

    # ------------------------------------------------------------------
    # Filesystem helpers
    # ------------------------------------------------------------------

    async def _is_actively_migrating(self, db_path: str) -> bool:
        """
        Check whether a path is the source of a task that has not settled yet.

        Narrower than ``is_file_locked``, which also covers targets; this one answers
        "is this file already on its way out?".

        :param db_path: Path in DB format.
        :type db_path: str
        :return: True if a non-terminal task has this path as its source.
        :rtype: bool
        """
        active_statuses = [
            s.value for s in TaskStatus if s not in TaskStateMachine.TERMINAL_STATUSES
        ]
        count = await MigrationTaskModel.find(
            {
                "status": {"$in": active_statuses},
                "source_path": db_path,
            }
        ).count()
        return count > 0

    @staticmethod
    def _cleanup_target(handler: BaseResourceHandler, target_fs: str) -> None:
        """
        Delete a partially written target file, best effort.

        Never raises: this runs on paths that are already handling a cancellation, a
        failure or a crash recovery, where a cleanup problem must not mask the original
        cause.

        :param handler: Storage handler for the target category.
        :type handler: BaseResourceHandler
        :param target_fs: Target path in FS format.
        :type target_fs: str
        :rtype: None
        """
        try:
            if handler.file_exists(target_fs):
                handler.delete_file(target_fs)
        except Exception as e:
            logger.warning(f"Failed to cleanup target file {target_fs}: {e}")

    @staticmethod
    def _generate_unique_name(handler: BaseResourceHandler, dir_fs: str, filename: str) -> str:
        """
        Find a free ``name(n).ext`` variant in a directory, for the "rename" conflict
        strategy.

        :param handler: Storage handler for the directory's category.
        :type handler: BaseResourceHandler
        :param dir_fs: Target directory in FS format.
        :type dir_fs: str
        :param filename: Desired file name, including extension.
        :type filename: str
        :return: Full FS-format path of the first name not already taken.
        :rtype: str
        """
        name_no_ext = handler.get_filename_without_extension(filename)
        ext = handler.get_file_extension(filename)
        suffix = f".{ext}" if ext else ""
        counter = 1
        while True:
            candidate = handler.join_path(dir_fs, f"{name_no_ext}({counter}){suffix}")
            if not handler.file_exists(candidate):
                return candidate
            counter += 1

    # ------------------------------------------------------------------
    # Phase: PROCESSING
    # ------------------------------------------------------------------

    async def _execute_processing(
        self, task: MigrationTaskModel
    ) -> AsyncGenerator[ProgressFrame, None]:
        """
        Phase 1 — stream the file from source to target, reporting progress each second.

        ``write_file_streaming`` consumes its whole iterator inside a single await, which
        would keep this generator's frame suspended for the entire copy and make it unable
        to yield anything. Running the copy as its own Task is what allows progress to be
        reported while the transfer is in flight; ``counting_reader`` sits in between,
        tallying bytes and checking for cancellation on every chunk.

        On success the task moves to PROCESS_DONE. On cancellation or failure the partial
        target file is removed, since this phase always restarts from the beginning.

        :param task: The task being executed.
        :type task: MigrationTaskModel
        :yield: A frame when the copy starts, one per second while it runs, and a final
            frame on completion or cancellation.
        :rtype: AsyncGenerator[ProgressFrame, None]
        :raises Exception: Any copy failure, re-raised after the target is cleaned up, so
            the state machine can record it as FAILED.
        """
        source_handler, target_handler, source_fs, target_fs = self._resolve_paths(task)

        await self._update_task_status(task, TaskStatus.PROCESSING)
        yield self._make_progress(task, message="Starting copy")

        task_id = str(task.id)
        bytes_copied = 0

        async def counting_reader():
            """Feeds the writer while counting bytes and watching for cancellation."""
            nonlocal bytes_copied
            async for chunk in source_handler.read_file_streaming(source_fs):
                if self._cancel_requested.get(task_id):
                    raise _MigrationCancelled()
                bytes_copied += len(chunk)
                yield chunk

        copy_task = asyncio.create_task(
            target_handler.write_file_streaming(target_fs, counting_reader())
        )

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
            self._cleanup_target(target_handler, target_fs)
            await self._update_task_status(task, TaskStatus.CANCELLED)
            self._cancel_requested.pop(task_id, None)
            yield self._make_progress(task, current=bytes_copied, message="cancelled")
            return
        except Exception:
            self._cleanup_target(target_handler, target_fs)
            raise

        await self._update_task_status(task, TaskStatus.PROCESS_DONE, bytes_transferred=task.file_size)
        yield self._make_progress(task, current=task.file_size, message="Copy completed")

    # ------------------------------------------------------------------
    # Phase: UPDATING_DB
    # ------------------------------------------------------------------

    async def _execute_db_update(self, task: MigrationTaskModel) -> None:
        """
        Phase 2 — repoint the video record at its new path and category.

        Written to be idempotent, because recovery and retry can both replay this phase
        after it already succeeded. If no record matches the source path, that is only
        accepted as "already done" when a record really does exist at the target;
        otherwise the record is genuinely missing and the task must fail.

        Under the ``"overwrite"`` strategy the record occupying the target path is deleted
        first — unless it is the very record being moved, which is what a replay looks like.

        :param task: The task being executed.
        :type task: MigrationTaskModel
        :rtype: None
        :raises Exception: If the video record is at neither the source nor the target path.
        """
        await self._update_task_status(task, TaskStatus.UPDATING_DB)

        target_path = task.renamed_target_path or task.target_path

        video = await VideoModel.find_one({"path": task.source_path})

        if video is None:
            # An interrupted or retried run may already have moved the record. Only treat
            # that as success if the target record really is there.
            migrated = await VideoModel.find_one({"path": target_path})
            if migrated is None:
                raise Exception(f"Source video record not found: {task.source_path}")
            logger.info(f"Task {task.id}: video record already at target, skipping DB update")
            await self._update_task_status(task, TaskStatus.DB_UPDATED)
            return

        if task.conflict_strategy == "overwrite":
            conflicting = await VideoModel.find_one({"path": target_path})
            if conflicting is not None and conflicting.id != video.id:
                await conflicting.delete()

        video.path = target_path
        video.category = task.target_category
        await video.save()

        await self._update_task_status(task, TaskStatus.DB_UPDATED)

    # ------------------------------------------------------------------
    # Phase: DELETING_SOURCE
    # ------------------------------------------------------------------

    async def _execute_fs_cleanup(self, task: MigrationTaskModel) -> str | None:
        """
        Phase 3 — delete the original and refresh both directories' metadata.

        Everything here is best effort. By this point the file has been copied and the
        database already points at the new location, so the migration has succeeded; a
        leftover source file or a stale directory aggregate is worth a warning, not a
        failure. The task therefore always ends COMPLETED.

        :param task: The task being executed.
        :type task: MigrationTaskModel
        :return: A warning to show the user if the source could not be deleted, else None.
            Metadata refresh failures are only logged.
        :rtype: str | None
        """
        source_handler, target_handler, source_fs, _ = self._resolve_paths(task)

        await self._update_task_status(task, TaskStatus.DELETING_SOURCE)

        warning = None
        try:
            source_handler.delete_file(source_fs)
        except Exception as e:
            warning = f"Source file deletion failed: {e}"
            logger.warning(f"Task {task.id}: {warning}")

        try:
            source_dir_db = source_handler.dirname(task.source_path)
            source_dir_abs = AbsolutePath.from_existing_path(
                source_dir_db, task.source_category, source_handler
            )
            await self.dirMetadataService.update_directory_metadata_forward(source_dir_abs)
        except Exception as e:
            logger.warning(f"Task {task.id}: Source directory metadata update failed: {e}")

        try:
            target_path = task.renamed_target_path or task.target_path
            target_dir_db = target_handler.dirname(target_path)
            target_dir_abs = AbsolutePath.from_existing_path(
                target_dir_db, task.target_category, target_handler
            )
            await self.dirMetadataService.update_directory_metadata_forward(target_dir_abs)
        except Exception as e:
            logger.warning(f"Task {task.id}: Target directory metadata update failed: {e}")

        await self._update_task_status(task, TaskStatus.COMPLETED)
        return warning