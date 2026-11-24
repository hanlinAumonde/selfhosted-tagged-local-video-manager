"""Batch migration: one batch document over N ordinary migration tasks.

Children are plain ``MigrationTaskModel`` documents carrying a ``batch_id``, so path locks,
duplicate prevention and per-file retry all keep working unchanged. The batch's state is
never stored; it is counted from its children.

Fake tree (``local_resource_dir``)::

    movie_a.mp4         # 100 bytes
    movie_b.mp4         # 200 bytes
    subdir/movie_c.mp4  # 300 bytes
"""

import pytest

from src.errors import InputValidationError
from src.features.migration.migration_batch import BatchWindow
from src.features.migration.migration_batch_model import MigrationBatchModel
from src.features.migration.migration_task_model import MigrationTaskModel
from src.platform.jobs.task_model import TaskStatus
from src.platform.storage.absolute_path import AbsolutePath
from tests.unit.features.migration.batch_helpers import (
    SOURCE_ROOT,
    TARGET_ROOT,
    add_child,
    make_batch,
)

pytestmark = pytest.mark.unit

UNKNOWN_BATCH = "507f1f77bcf86cd799439011"


def _source(handler_service, relative: str) -> AbsolutePath:
    handler = handler_service.get_handler("Test-category")
    return AbsolutePath.from_existing_path(
        f"{SOURCE_ROOT}/{relative}", category="Test-category", handler=handler
    )


def _target_dir(handler_service) -> AbsolutePath:
    handler = handler_service.get_handler("Target-category")
    return AbsolutePath.from_existing_path(TARGET_ROOT, category="Target-category", handler=handler)


def _three_sources(handler_service) -> list[AbsolutePath]:
    return [
        _source(handler_service, "movie_a.mp4"),
        _source(handler_service, "movie_b.mp4"),
        _source(handler_service, "subdir/movie_c.mp4"),
    ]


async def _drain(gen) -> None:
    async for _ in gen:
        pass


class TestBatchPreflight:
    async def test_preflight_reports_each_file_and_their_total_size(
        self, batch_svc, init_db, two_cat_handler_service,
    ):
        """
        Scenario: every file is checked and the sizes are added up
          Given videos "movie_a.mp4" (100 bytes), "movie_b.mp4" (200 bytes)
            and "subdir/movie_c.mp4" (300 bytes) in Test-category
          And an empty target directory in Target-category
          When the batch preflight runs for the three files into that directory
          Then it reports one result per file, each valid
          And the total size is 600 bytes
          And the batch is valid
        """
        result = await batch_svc.preflight(
            _three_sources(two_cat_handler_service), _target_dir(two_cat_handler_service)
        )

        assert [item.source_file_size for item in result.items] == [100, 200, 300]
        assert all(item.valid for item in result.items)
        assert result.total_size == 600
        assert result.valid is True

    async def test_files_that_fit_one_by_one_but_not_together_are_insufficient(
        self, batch_svc, init_db, two_cat_handler_service, monkeypatch,
    ):
        """
        Scenario: the target has room for each file but not for all of them
          Given videos "movie_a.mp4" (100 bytes), "movie_b.mp4" (200 bytes)
            and "subdir/movie_c.mp4" (300 bytes)
          And the target directory reports 400 bytes available
          When the batch preflight runs for the three files into that directory
          Then each file's own result is valid
          But the batch's space is reported insufficient
          And the batch is not valid
        """
        target_handler = two_cat_handler_service.get_handler("Target-category")

        async def four_hundred_bytes(path):
            return 400

        monkeypatch.setattr(target_handler, "get_available_space", four_hundred_bytes)

        result = await batch_svc.preflight(
            _three_sources(two_cat_handler_service), _target_dir(two_cat_handler_service)
        )

        assert all(item.valid for item in result.items)
        assert result.space_available == 400
        assert result.space_sufficient is False
        assert result.valid is False

    async def test_a_file_already_migrating_makes_the_batch_invalid(
        self, batch_svc, init_db, two_cat_handler_service, task_factory,
    ):
        """
        Scenario: one file of the batch is already on its way out
          Given videos "movie_a.mp4" and "movie_b.mp4"
          And "movie_b.mp4" is the source of a PROCESSING migration task
          When the batch preflight runs for both files
          Then the result for "movie_a.mp4" is valid
          And the result for "movie_b.mp4" reports already_migrating
          And the batch is not valid
        """
        await task_factory(
            source_path=f"{SOURCE_ROOT}/movie_b.mp4",
            target_path=f"{TARGET_ROOT}/elsewhere/movie_b.mp4",
            status=TaskStatus.PROCESSING,
        )
        sources = [
            _source(two_cat_handler_service, "movie_a.mp4"),
            _source(two_cat_handler_service, "movie_b.mp4"),
        ]

        result = await batch_svc.preflight(sources, _target_dir(two_cat_handler_service))

        movie_a, movie_b = result.items
        assert movie_a.valid is True
        assert movie_b.already_migrating is True
        assert result.valid is False


class TestCreateBatch:
    async def test_creates_one_pending_child_per_file_under_one_batch(
        self, batch_svc, init_db, two_cat_handler_service,
    ):
        """
        Scenario: a batch is created over three files
          Given videos "movie_a.mp4", "movie_b.mp4" and "subdir/movie_c.mp4"
          And an empty target directory in Target-category
          When a batch is created for the three files into that directory
          Then one batch document is stored with that target directory
          And three PENDING migration tasks are stored, each with that batch's id
          And their target paths are the target directory plus each file's name
          And nothing is reported as skipped
        """
        creation = await batch_svc.create_batch(
            _three_sources(two_cat_handler_service), _target_dir(two_cat_handler_service), None
        )

        stored_batches = await MigrationBatchModel.find_all().to_list()
        assert [b.target_dir for b in stored_batches] == [TARGET_ROOT]
        assert creation.batch.id == stored_batches[0].id

        children = await MigrationTaskModel.find(
            MigrationTaskModel.batch_id == creation.batch.id
        ).to_list()
        assert sorted(c.target_path for c in children) == [
            f"{TARGET_ROOT}/movie_a.mp4",
            f"{TARGET_ROOT}/movie_b.mp4",
            f"{TARGET_ROOT}/movie_c.mp4",
        ]
        assert {c.status for c in children} == {TaskStatus.PENDING}
        assert len(creation.tasks) == 3
        assert creation.skipped == []

    async def test_file_already_migrating_is_skipped_and_the_rest_are_created(
        self, batch_svc, init_db, two_cat_handler_service, task_factory,
    ):
        """
        Scenario: a file that already has an active task is skipped, not fatal
          Given videos "movie_a.mp4", "movie_b.mp4" and "subdir/movie_c.mp4"
          And "movie_b.mp4" is the source of a PENDING migration task outside any batch
          When a batch is created for the three files
          Then the batch has children for "movie_a.mp4" and "movie_c.mp4"
          And "movie_b.mp4" is reported as skipped with a reason
          And the existing task for "movie_b.mp4" is left untouched, without a batch id
        """
        existing = await task_factory(
            source_path=f"{SOURCE_ROOT}/movie_b.mp4",
            target_path=f"{TARGET_ROOT}/elsewhere/movie_b.mp4",
        )

        creation = await batch_svc.create_batch(
            _three_sources(two_cat_handler_service), _target_dir(two_cat_handler_service), None
        )

        assert sorted(t.source_path for t in creation.tasks) == [
            f"{SOURCE_ROOT}/movie_a.mp4",
            f"{SOURCE_ROOT}/subdir/movie_c.mp4",
        ]
        assert [s.source_path for s in creation.skipped] == [f"{SOURCE_ROOT}/movie_b.mp4"]
        assert creation.skipped[0].reason
        untouched = await MigrationTaskModel.get(existing.id)
        assert untouched.batch_id is None
        assert untouched.target_path == f"{TARGET_ROOT}/elsewhere/movie_b.mp4"

    async def test_conflict_with_skip_strategy_skips_only_that_file(
        self, batch_svc, init_db, two_cat_handler_service, target_dir,
    ):
        """
        Scenario: under the skip strategy only the conflicting file is left out
          Given videos "movie_a.mp4" and "movie_b.mp4"
          And the target directory already holds a file named "movie_a.mp4"
          When a batch is created for both files with conflict strategy "skip"
          Then the batch has one child, for "movie_b.mp4"
          And "movie_a.mp4" is reported as skipped
        """
        (target_dir / "movie_a.mp4").write_bytes(b"older")
        sources = [
            _source(two_cat_handler_service, "movie_a.mp4"),
            _source(two_cat_handler_service, "movie_b.mp4"),
        ]

        creation = await batch_svc.create_batch(sources, _target_dir(two_cat_handler_service), "skip")

        assert [t.source_path for t in creation.tasks] == [f"{SOURCE_ROOT}/movie_b.mp4"]
        assert [s.source_path for s in creation.skipped] == [f"{SOURCE_ROOT}/movie_a.mp4"]

    async def test_rename_strategy_renames_only_the_conflicting_file(
        self, batch_svc, init_db, two_cat_handler_service, target_dir,
    ):
        """
        Scenario: under the rename strategy each conflicting file gets a free name
          Given videos "movie_a.mp4" and "movie_b.mp4"
          And the target directory already holds a file named "movie_a.mp4"
          When a batch is created for both files with conflict strategy "rename"
          Then the child for "movie_a.mp4" targets "movie_a(1).mp4"
          And the child for "movie_b.mp4" targets "movie_b.mp4"
        """
        (target_dir / "movie_a.mp4").write_bytes(b"older")
        sources = [
            _source(two_cat_handler_service, "movie_a.mp4"),
            _source(two_cat_handler_service, "movie_b.mp4"),
        ]

        creation = await batch_svc.create_batch(sources, _target_dir(two_cat_handler_service), "rename")

        targets = {t.source_path: t.target_path for t in creation.tasks}
        assert targets == {
            f"{SOURCE_ROOT}/movie_a.mp4": f"{TARGET_ROOT}/movie_a(1).mp4",
            f"{SOURCE_ROOT}/movie_b.mp4": f"{TARGET_ROOT}/movie_b.mp4",
        }

    async def test_no_creatable_file_leaves_no_batch_behind(
        self, batch_svc, init_db, two_cat_handler_service, task_factory,
    ):
        """
        Scenario: when every file is skipped there is no batch
          Given videos "movie_a.mp4" and "movie_b.mp4"
          And both are sources of active migration tasks outside any batch
          When a batch is created for both files
          Then no batch is returned
          And no batch document is stored
          And both files are reported as skipped
        """
        for name, status in (("movie_a", TaskStatus.PENDING), ("movie_b", TaskStatus.PROCESSING)):
            await task_factory(
                source_path=f"{SOURCE_ROOT}/{name}.mp4",
                target_path=f"{TARGET_ROOT}/elsewhere/{name}.mp4",
                status=status,
            )
        sources = [
            _source(two_cat_handler_service, "movie_a.mp4"),
            _source(two_cat_handler_service, "movie_b.mp4"),
        ]

        creation = await batch_svc.create_batch(sources, _target_dir(two_cat_handler_service), None)

        assert creation.batch is None
        assert await MigrationBatchModel.find_all().count() == 0
        assert len(creation.skipped) == 2


class TestBatchSummary:
    async def test_summary_counts_children_by_outcome(self, batch_svc, task_factory):
        """
        Scenario: the batch's state is counted from its children
          Given a batch whose children are one PENDING, one PROCESSING, one COMPLETED,
            one FAILED and one CANCELLED
          And a migration task outside the batch that is COMPLETED
          When the batch is summarized
          Then the summary reports total 5, active 2, completed 1, failed 1, cancelled 1
          And the summary is not settled
        """
        batch = await make_batch()
        for name, status in (
            ("a", TaskStatus.PENDING),
            ("b", TaskStatus.PROCESSING),
            ("c", TaskStatus.COMPLETED),
            ("d", TaskStatus.FAILED),
            ("e", TaskStatus.CANCELLED),
        ):
            await add_child(task_factory, batch, name, status)
        await task_factory(
            source_path=f"{SOURCE_ROOT}/outsider.mp4",
            target_path=f"{TARGET_ROOT}/outsider.mp4",
            status=TaskStatus.COMPLETED,
        )

        summary = await batch_svc.summarize(str(batch.id))

        assert (summary.total, summary.active, summary.completed, summary.failed, summary.cancelled) == (5, 2, 1, 1, 1)
        assert summary.settled is False

    async def test_summary_of_a_batch_whose_children_all_ended_is_settled(self, batch_svc, task_factory):
        """
        Scenario: a batch is settled once no child is still active
          Given a batch whose children are one COMPLETED, one FAILED and one CANCELLED
          When the batch is summarized
          Then the summary reports active 0
          And the summary is settled
        """
        batch = await make_batch()
        for name, status in (("a", TaskStatus.COMPLETED), ("b", TaskStatus.FAILED), ("c", TaskStatus.CANCELLED)):
            await add_child(task_factory, batch, name, status)

        summary = await batch_svc.summarize(str(batch.id))

        assert summary.active == 0
        assert summary.settled is True

    async def test_summary_of_an_unknown_batch_is_none(self, batch_svc, init_db):
        """
        Scenario: summarizing a batch that does not exist
          Given no batch with id "507f1f77bcf86cd799439011"
          When that batch is summarized
          Then the summary is None
        """
        assert await batch_svc.summarize(UNKNOWN_BATCH) is None


class TestCancelBatch:
    async def test_cancel_settles_queued_children_and_flags_running_ones(self, batch_svc, task_factory):
        """
        Scenario: cancelling a batch cancels each unfinished child its own way
          Given a batch with children "movie_a.mp4" PENDING, "movie_b.mp4" PROCESSING
            and "movie_c.mp4" COMPLETED
          When the batch is cancelled
          Then "movie_a.mp4" is stored as CANCELLED
          And "movie_b.mp4" is still PROCESSING with cancel_requested True
          And "movie_c.mp4" is still COMPLETED
          And the ids of the settled children are reported as ["movie_a.mp4"'s id]
        """
        batch = await make_batch()
        queued = await add_child(task_factory, batch, "movie_a", TaskStatus.PENDING)
        running = await add_child(task_factory, batch, "movie_b", TaskStatus.PROCESSING)
        done = await add_child(task_factory, batch, "movie_c", TaskStatus.COMPLETED, sub_dir="subdir/")

        settled = await batch_svc.cancel_batch(str(batch.id))

        assert (await MigrationTaskModel.get(queued.id)).status == TaskStatus.CANCELLED
        stored_running = await MigrationTaskModel.get(running.id)
        assert stored_running.status == TaskStatus.PROCESSING
        assert stored_running.cancel_requested is True
        assert (await MigrationTaskModel.get(done.id)).status == TaskStatus.COMPLETED
        assert settled == [str(queued.id)]

    async def test_children_past_the_copy_are_left_to_finish(self, batch_svc, task_factory):
        """
        Scenario: a child that can no longer be cancelled does not stop the others
          Given a batch with children "movie_a.mp4" COMMITTING and "movie_b.mp4" PENDING
          When the batch is cancelled
          Then "movie_a.mp4" is still COMMITTING with cancel_requested False
          And "movie_b.mp4" is stored as CANCELLED
        """
        batch = await make_batch()
        committing = await add_child(task_factory, batch, "movie_a", TaskStatus.COMMITTING)
        queued = await add_child(task_factory, batch, "movie_b", TaskStatus.PENDING)

        await batch_svc.cancel_batch(str(batch.id))

        stored = await MigrationTaskModel.get(committing.id)
        assert stored.status == TaskStatus.COMMITTING
        assert stored.cancel_requested is False
        assert (await MigrationTaskModel.get(queued.id)).status == TaskStatus.CANCELLED

    async def test_cancelling_an_unknown_batch_is_rejected(self, batch_svc, init_db):
        """
        Scenario: cancelling a batch that does not exist
          Given no batch with id "507f1f77bcf86cd799439011"
          When that batch is cancelled
          Then InputValidationError is raised
        """
        with pytest.raises(InputValidationError):
            await batch_svc.cancel_batch(UNKNOWN_BATCH)


class TestRetryBatch:
    async def test_retry_requeues_only_failed_children(self, batch_svc, task_factory):
        """
        Scenario: retrying a batch retries its failed children and nothing else
          Given a batch with children "movie_a.mp4" FAILED at COMMITTING,
            "movie_b.mp4" FAILED at PROCESSING and "movie_c.mp4" COMPLETED
          When the batch is retried
          Then "movie_a.mp4" is stored as PENDING with resume_from COMMITTING
          And "movie_b.mp4" is stored as PENDING with resume_from PROCESSING
          And "movie_c.mp4" is still COMPLETED
          And the ids of "movie_a.mp4" and "movie_b.mp4" are reported as requeued
        """
        batch = await make_batch()
        failed_commit = await add_child(
            task_factory, batch, "movie_a", TaskStatus.FAILED, failed_step=TaskStatus.COMMITTING.value
        )
        failed_copy = await add_child(
            task_factory, batch, "movie_b", TaskStatus.FAILED, failed_step=TaskStatus.PROCESSING.value
        )
        done = await add_child(task_factory, batch, "movie_c", TaskStatus.COMPLETED, sub_dir="subdir/")

        requeued = await batch_svc.retry_batch(str(batch.id))

        stored_a = await MigrationTaskModel.get(failed_commit.id)
        assert (stored_a.status, stored_a.resume_from) == (TaskStatus.PENDING, TaskStatus.COMMITTING)
        stored_b = await MigrationTaskModel.get(failed_copy.id)
        assert (stored_b.status, stored_b.resume_from) == (TaskStatus.PENDING, TaskStatus.PROCESSING)
        assert (await MigrationTaskModel.get(done.id)).status == TaskStatus.COMPLETED
        assert sorted(requeued) == sorted([str(failed_commit.id), str(failed_copy.id)])

    async def test_retrying_an_unknown_batch_is_rejected(self, batch_svc, init_db):
        """
        Scenario: retrying a batch that does not exist
          Given no batch with id "507f1f77bcf86cd799439011"
          When that batch is retried
          Then InputValidationError is raised
        """
        with pytest.raises(InputValidationError):
            await batch_svc.retry_batch(UNKNOWN_BATCH)


class TestNextToDispatch:
    async def test_picks_the_oldest_pending_children_that_are_not_held(self, batch_svc, task_factory):
        """
        Scenario: choosing which children to send next
          Given a batch with children created in order:
            "a" COMPLETED, "b" PENDING, "c" PENDING, "d" PENDING, "e" CANCELLED
          And a PENDING migration task outside the batch
          When the next 2 children are requested, excluding "b" which is already held
          Then "c" and "d" are returned, in that order
        """
        batch = await make_batch()
        children = {}
        for name, status in (
            ("a", TaskStatus.COMPLETED),
            ("b", TaskStatus.PENDING),
            ("c", TaskStatus.PENDING),
            ("d", TaskStatus.PENDING),
            ("e", TaskStatus.CANCELLED),
        ):
            children[name] = await add_child(task_factory, batch, name, status)
        await task_factory(
            source_path=f"{SOURCE_ROOT}/outsider.mp4", target_path=f"{TARGET_ROOT}/outsider.mp4"
        )

        picked = await batch_svc.next_to_dispatch(
            str(batch.id), held={str(children["b"].id)}, limit=2
        )

        assert picked == [str(children["c"].id), str(children["d"].id)]


class TestDirectoryMetadataSettledOnce:
    async def test_a_batch_child_does_not_refresh_directory_metadata_itself(
        self, two_cat_migration_svc, refreshed_dirs, task_factory, video_factory,
        local_resource_dir, target_dir,
    ):
        """
        Scenario: a child leaves the directory refresh to its batch
          Given a batch with one PENDING child migrating "movie_a.mp4" to Target-category
          When that child runs to COMPLETED
          Then the target file exists and the source file is gone
          And no directory metadata was refreshed
        """
        await video_factory(name="movie_a", path=f"{SOURCE_ROOT}/movie_a.mp4")
        batch = await make_batch()
        child = await add_child(task_factory, batch, "movie_a")

        await _drain(two_cat_migration_svc.run_task(str(child.id)))

        assert (await MigrationTaskModel.get(child.id)).status == TaskStatus.COMPLETED
        assert (target_dir / "movie_a.mp4").exists()
        assert not (local_resource_dir / "movie_a.mp4").exists()
        assert refreshed_dirs == []

    async def test_a_task_outside_any_batch_still_refreshes_its_directories(
        self, two_cat_migration_svc, refreshed_dirs, task_factory, video_factory,
    ):
        """
        Scenario: a single migration keeps refreshing both directories itself
          Given a PENDING migration task for "movie_a.mp4" outside any batch
          When that task runs to COMPLETED
          Then the source directory's and the target directory's metadata were refreshed
        """
        await video_factory(name="movie_a", path=f"{SOURCE_ROOT}/movie_a.mp4")
        task = await task_factory(
            source_path=f"{SOURCE_ROOT}/movie_a.mp4", target_path=f"{TARGET_ROOT}/movie_a.mp4"
        )

        await _drain(two_cat_migration_svc.run_task(str(task.id)))

        assert sorted(refreshed_dirs) == sorted([
            ("Test-category", SOURCE_ROOT),
            ("Target-category", TARGET_ROOT),
        ])

    async def test_settling_a_finished_batch_refreshes_each_directory_once(
        self, batch_svc, refreshed_dirs, task_factory,
    ):
        """
        Scenario: the directories a batch touched are refreshed once each
          Given a batch whose children moved "movie_a.mp4" and "movie_b.mp4" from the
            Test-resource root and "subdir/movie_c.mp4" from "subdir", all COMPLETED,
            into one target directory
          When the batch is settled
          Then the Test-resource root, "subdir" and the target directory are each
            refreshed exactly once
        """
        batch = await make_batch()
        await add_child(task_factory, batch, "movie_a", TaskStatus.COMPLETED)
        await add_child(task_factory, batch, "movie_b", TaskStatus.COMPLETED)
        await add_child(task_factory, batch, "movie_c", TaskStatus.COMPLETED, sub_dir="subdir/")

        await batch_svc.settle(str(batch.id))

        assert sorted(refreshed_dirs) == sorted([
            ("Test-category", SOURCE_ROOT),
            ("Test-category", f"{SOURCE_ROOT}/subdir"),
            ("Target-category", TARGET_ROOT),
        ])

    async def test_settling_skips_the_source_directories_of_children_that_did_not_move(
        self, batch_svc, refreshed_dirs, task_factory,
    ):
        """
        Scenario: only completed children moved anything
          Given a batch whose children are "movie_a.mp4" from the root COMPLETED
            and "subdir/movie_c.mp4" from "subdir" CANCELLED
          When the batch is settled
          Then the root and the target directory are refreshed
          And "subdir" is not refreshed
        """
        batch = await make_batch()
        await add_child(task_factory, batch, "movie_a", TaskStatus.COMPLETED)
        await add_child(task_factory, batch, "movie_c", TaskStatus.CANCELLED, sub_dir="subdir/")

        await batch_svc.settle(str(batch.id))

        assert sorted(refreshed_dirs) == sorted([
            ("Test-category", SOURCE_ROOT),
            ("Target-category", TARGET_ROOT),
        ])

    async def test_settling_an_unfinished_batch_refreshes_nothing(
        self, batch_svc, refreshed_dirs, task_factory,
    ):
        """
        Scenario: a batch with an active child is not settled yet
          Given a batch whose children are "movie_a.mp4" COMPLETED and "movie_b.mp4" PROCESSING
          When the batch is settled
          Then no directory metadata is refreshed
        """
        batch = await make_batch()
        await add_child(task_factory, batch, "movie_a", TaskStatus.COMPLETED)
        await add_child(task_factory, batch, "movie_b", TaskStatus.PROCESSING)

        await batch_svc.settle(str(batch.id))

        assert refreshed_dirs == []


class TestBatchWindow:
    def test_admits_two_children_of_a_batch_and_refuses_the_third(self):
        """
        Scenario: at most two children of one batch are held at a time
          Given an empty batch window
          When children "a", "b" and "c" of batch "B" ask to be admitted in that order
          Then "a" and "b" are admitted
          And "c" is refused
        """
        window = BatchWindow(2)

        assert [window.admit("B", child) for child in ("a", "b", "c")] == [True, True, False]

    def test_a_redelivery_of_an_admitted_child_is_refused(self):
        """
        Scenario: a second delivery of a held child is not a second holder
          Given a batch window holding child "a" of batch "B"
          When child "a" of batch "B" asks to be admitted again
          Then it is refused
          And the window still holds only "a" for batch "B"
        """
        window = BatchWindow(2)
        window.admit("B", "a")

        assert window.admit("B", "a") is False
        assert window.held("B") == {"a"}

    def test_releasing_a_child_frees_its_place(self):
        """
        Scenario: a released place goes to the next child
          Given a batch window holding children "a" and "b" of batch "B"
          When "a" is released and then "c" asks to be admitted
          Then "c" is admitted
          And the window holds "b" and "c" for batch "B"
        """
        window = BatchWindow(2)
        window.admit("B", "a")
        window.admit("B", "b")

        window.release("B", "a")

        assert window.admit("B", "c") is True
        assert window.held("B") == {"b", "c"}

    def test_windows_of_different_batches_are_independent(self):
        """
        Scenario: one busy batch does not hold up another
          Given a batch window holding children "a" and "b" of batch "B1"
          When child "x" of batch "B2" asks to be admitted
          Then "x" is admitted
        """
        window = BatchWindow(2)
        window.admit("B1", "a")
        window.admit("B1", "b")

        assert window.admit("B2", "x") is True
