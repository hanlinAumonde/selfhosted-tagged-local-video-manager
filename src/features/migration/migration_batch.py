from dataclasses import dataclass
import time

from beanie import PydanticObjectId
from beanie.operators import NotIn
from bson import ObjectId
from bson.errors import InvalidId

from src.errors import InputValidationError
from src.features.migration.migration_batch_model import MigrationBatchModel
from src.features.migration.migration_service import MigrationPreflightResult, MigrationService
from src.features.migration.migration_task import MigrationTaskModel
from src.logger import get_logger
from src.platform.jobs.state_machine import TaskStateMachine
from src.platform.jobs.task_model import TaskStatus
from src.platform.storage.absolute_path import AbsolutePath

logger = get_logger("migration_batch")

_TERMINAL = [s.value for s in TaskStateMachine.TERMINAL_STATUSES]

@dataclass
class BatchPreflightResult:
    valid: bool
    #: One per source, in the order given.
    items: list[MigrationPreflightResult]
    #: Bytes the batch would add to the target; files that will not move are left out.
    total_size: int
    space_available: int | None
    space_sufficient: bool | None


@dataclass(frozen=True)
class SkippedSource:
    source_path: str
    reason: str


@dataclass
class BatchCreation:
    #: None when no file could be added, in which case no batch is stored.
    batch: MigrationBatchModel | None
    tasks: list[MigrationTaskModel]
    skipped: list[SkippedSource]


@dataclass(frozen=True)
class BatchSummary:
    batch_id: str
    total: int
    active: int
    completed: int
    failed: int
    cancelled: int

    @property
    def settled(self) -> bool:
        """Whether no child of the batch is still waiting or running."""
        return self.active == 0


class BatchWindow:
    """
    Which children of each batch this worker holds — waiting for a copy slot or running.

    In memory because exactly one worker process drains the migration queue: what it holds
    is all that is held anywhere.
    """

    def __init__(self, size: int):
        self._size = size
        self._held: dict[str, set[str]] = {}

    def admit(self, batch_id: str, task_id: str) -> bool:
        """
        Take a place for a child, if the batch has one free.

        :param batch_id: The child's batch.
        :type batch_id: str
        :param task_id: The child being delivered.
        :type task_id: str
        :return: True if the caller now holds the place and must ``release`` it. False if
            the batch is full, or this child is already held — a redelivery, which must
            neither run twice nor free the place its first delivery holds.
        :rtype: bool
        """
        held = self._held.setdefault(batch_id, set())
        if task_id in held or len(held) >= self._size:
            return False
        held.add(task_id)
        return True

    def release(self, batch_id: str, task_id: str) -> None:
        """
        Give back the place a child took with ``admit``. Releasing a child that holds no
        place is a no-op.

        :param batch_id: The child's batch.
        :type batch_id: str
        :param task_id: The child that finished or gave up its place.
        :type task_id: str
        """
        held = self._held.get(batch_id)
        if held is None:
            return
        held.discard(task_id)
        if not held:
            del self._held[batch_id]

    def held(self, batch_id: str) -> set[str]:
        """
        The children of a batch holding a place right now.

        :param batch_id: The batch to look at.
        :type batch_id: str
        :return: A copy, so the caller may keep it across later admits and releases.
        :rtype: set[str]
        """
        return set(self._held.get(batch_id, ()))

    def free(self, batch_id: str) -> int:
        """
        How many more children of a batch could be admitted now.

        :param batch_id: The batch to look at.
        :type batch_id: str
        :rtype: int
        """
        return self._size - len(self._held.get(batch_id, ()))


def _object_id(batch_id: str) -> ObjectId | None:
    try:
        return ObjectId(batch_id)
    except (InvalidId, TypeError):
        return None


class MigrationBatchService:
    """Creates, inspects and steers batches; each child is run by ``MigrationService``."""

    def __init__(self, migration_service: MigrationService):
        self._migrations = migration_service

    async def preflight(
        self, sources: list[AbsolutePath], target_dir: AbsolutePath
    ) -> BatchPreflightResult:
        """
        Check every file as a single migration would, then check that they fit together.

        :param sources: The video files to move.
        :type sources: list[AbsolutePath]
        :param target_dir: The directory to move them into.
        :type target_dir: AbsolutePath
        :return: Each file's findings plus the batch-wide space check. ``valid`` only
            when every file is valid and the target is not known to be too small.
        :rtype: BatchPreflightResult
        """
        items = [await self._migrations.preflight(source, target_dir) for source in sources]
        total_size = sum(
            item.source_file_size
            for item in items
            if not item.same_location and not item.already_migrating
        )
        space_available = await target_dir.handler.get_available_space(target_dir.FS_format_path())
        space_sufficient = None if space_available is None else space_available >= total_size
        return BatchPreflightResult(
            valid=all(item.valid for item in items) and space_sufficient is not False,
            items=items,
            total_size=total_size,
            space_available=space_available,
            space_sufficient=space_sufficient,
        )

    async def create_batch(
        self,
        sources: list[AbsolutePath],
        target_dir: AbsolutePath,
        conflict_strategy: str | None,
    ) -> BatchCreation:
        """
        Store a batch and one PENDING child per file that can be migrated.

        A file that cannot — already migrating, gone, or in conflict under ``"skip"`` —
        is reported and left out rather than failing the others. Nothing is dispatched.

        :param sources: The video files to move.
        :type sources: list[AbsolutePath]
        :param target_dir: The directory to move them into.
        :type target_dir: AbsolutePath
        :param conflict_strategy: Applied to every file whose name is taken at the target.
        :type conflict_strategy: str | None
        :return: The batch, its children, and the files left out with the reason.
        :rtype: BatchCreation
        """
        batch = MigrationBatchModel(
            target_dir=target_dir.DB_format_path(),
            target_category=target_dir.category,
            conflict_strategy=conflict_strategy,
            created_at=time.time(),
        )
        await batch.insert()

        tasks: list[MigrationTaskModel] = []
        skipped: list[SkippedSource] = []
        for source in sources:
            try:
                tasks.append(await self._migrations.create_task(
                    source, target_dir, conflict_strategy, batch_id=batch.id
                ))
            except InputValidationError as e:
                skipped.append(SkippedSource(source_path=source.DB_format_path(), reason=e.issue))

        if not tasks:
            await batch.delete()
            return BatchCreation(batch=None, tasks=[], skipped=skipped)
        logger.info(f"Migration batch created: {batch.id} | {len(tasks)} file(s), {len(skipped)} skipped")
        return BatchCreation(batch=batch, tasks=tasks, skipped=skipped)

    async def summarize(self, batch_id: str) -> BatchSummary | None:
        """
        Count a batch's children by outcome.

        :param batch_id: String form of the batch's ObjectId.
        :type batch_id: str
        :return: The counts, or None if there is no such batch.
        :rtype: BatchSummary | None
        """
        oid = _object_id(batch_id)
        if oid is None or await MigrationBatchModel.get(oid) is None:
            return None
        rows = await MigrationTaskModel.find(MigrationTaskModel.batch_id == oid).aggregate(
            [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
        ).to_list()
        by_status = {row["_id"]: row["count"] for row in rows}
        total = sum(by_status.values())
        completed = by_status.get(TaskStatus.COMPLETED.value, 0)
        failed = by_status.get(TaskStatus.FAILED.value, 0)
        cancelled = by_status.get(TaskStatus.CANCELLED.value, 0)
        return BatchSummary(
            batch_id=batch_id,
            total=total,
            active=total - completed - failed - cancelled,
            completed=completed,
            failed=failed,
            cancelled=cancelled,
        )

    async def cancel_batch(self, batch_id: str) -> list[str]:
        """
        Cancel every unfinished child the way a single cancel would.

        A child past its copy can no longer be cancelled and is left to finish; that does
        not stop the others.

        :param batch_id: String form of the batch's ObjectId.
        :type batch_id: str
        :return: Ids of the children settled as CANCELLED right here. Their worker will
            never announce it, so the caller must. Running children are only flagged.
        :rtype: list[str]
        :raises InputValidationError: If there is no such batch.
        """
        oid = await self._require(batch_id)
        children = await MigrationTaskModel.find(
            MigrationTaskModel.batch_id == oid, NotIn(MigrationTaskModel.status, _TERMINAL)
        ).to_list()

        settled: list[str] = []
        for child in children:
            try:
                task = await self._migrations.cancel_task(str(child.id))
            except InputValidationError as e:
                logger.info(f"Batch {batch_id}: child {child.id} left to finish: {e.issue}")
                continue
            if task.status == TaskStatus.CANCELLED:
                settled.append(str(task.id))
        return settled

    async def retry_batch(self, batch_id: str) -> list[str]:
        """
        Requeue every FAILED child, each from where it failed.

        :param batch_id: String form of the batch's ObjectId.
        :type batch_id: str
        :return: Ids of the requeued children, for the caller to dispatch.
        :rtype: list[str]
        :raises InputValidationError: If there is no such batch.
        """
        oid = await self._require(batch_id)
        failed = await MigrationTaskModel.find(
            MigrationTaskModel.batch_id == oid, MigrationTaskModel.status == TaskStatus.FAILED
        ).to_list()
        for child in failed:
            await self._migrations.prepare_retry(str(child.id))
        return [str(child.id) for child in failed]

    async def next_to_dispatch(self, batch_id: str, held: set[str], limit: int) -> list[str]:
        """
        The oldest PENDING children not already held, to fill the batch's free places.

        :param batch_id: String form of the batch's ObjectId.
        :type batch_id: str
        :param held: Ids of the children the worker holds.
        :type held: set[str]
        :param limit: How many places are free.
        :type limit: int
        :return: Up to ``limit`` child ids, oldest first.
        :rtype: list[str]
        """
        if limit <= 0:
            return []
        oid = _object_id(batch_id)
        children = await MigrationTaskModel.find(
            MigrationTaskModel.batch_id == oid,
            MigrationTaskModel.status == TaskStatus.PENDING,
            NotIn(MigrationTaskModel.id, [PydanticObjectId(i) for i in held]),
        ).sort("_id").limit(limit).to_list()
        return [str(child.id) for child in children]

    async def settle(self, batch_id: str) -> None:
        """
        Once no child is active, refresh each directory the batch moved files between.

        Children leave this to their batch so N files out of one directory recompute it
        once rather than N times. Calling it again after it has run only repeats a refresh.

        :param batch_id: String form of the batch's ObjectId.
        :type batch_id: str
        :rtype: None
        """
        summary = await self.summarize(batch_id)
        if summary is None or not summary.settled:
            return
        moved = await MigrationTaskModel.find(
            MigrationTaskModel.batch_id == ObjectId(batch_id),
            MigrationTaskModel.status == TaskStatus.COMPLETED,
        ).to_list()
        await self._migrations.refresh_directory_metadata(moved)

    @staticmethod
    async def _require(batch_id: str) -> ObjectId:
        oid = _object_id(batch_id)
        if oid is None or await MigrationBatchModel.get(oid) is None:
            raise InputValidationError(field="batch_id", issue="batch does not exist")
        return oid
