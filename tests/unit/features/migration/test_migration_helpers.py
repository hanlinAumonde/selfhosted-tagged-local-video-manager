"""Unit tests for MigrationService helper methods."""

import time
from pathlib import Path

import pytest

from src.features.migration.migration_task import MigrationTaskModel, TaskStatus
from src.platform.jobs.progress import ProgressFrame
from src.features.migration.migration_service import MigrationService

pytestmark = pytest.mark.unit


# =======================================================================
# _make_progress
# =======================================================================

class TestMakeProgress:
    def test_make_progress_basic(self, two_cat_migration_svc, init_db, task_factory):
        svc = two_cat_migration_svc

        task = MigrationTaskModel(
            source_path="a/b.mp4",
            source_category="Test-category",
            target_path="c/d.mp4",
            target_category="Target-category",
            file_name="b",
            file_size=200,
            bytes_transferred=100,
            status=TaskStatus.PROCESSING,
            created_at=time.time(),
            updated_at=time.time(),
        )

        progress = svc._make_progress(task, message="half done")
        assert progress.current == 100
        assert progress.total == 200
        assert progress.percentage == 50.0
        assert progress.message == "half done"

    def test_make_progress_with_override(self, two_cat_migration_svc):
        svc = two_cat_migration_svc

        task = MigrationTaskModel(
            source_path="a/b.mp4",
            source_category="Test-category",
            target_path="c/d.mp4",
            target_category="Target-category",
            file_name="b",
            file_size=100,
            bytes_transferred=0,
            status=TaskStatus.PROCESSING,
            created_at=time.time(),
            updated_at=time.time(),
        )

        progress = svc._make_progress(task, current=75)
        assert progress.current == 75
        assert progress.percentage == 75.0

    def test_make_progress_zero_size(self, two_cat_migration_svc):
        svc = two_cat_migration_svc

        task = MigrationTaskModel(
            source_path="a/b.mp4",
            source_category="Test-category",
            target_path="c/d.mp4",
            target_category="Target-category",
            file_name="b",
            file_size=0,
            bytes_transferred=0,
            status=TaskStatus.PROCESSING,
            created_at=time.time(),
            updated_at=time.time(),
        )

        progress = svc._make_progress(task)
        assert progress.percentage == 0


# =======================================================================
# _update_task_status
# =======================================================================

class TestUpdateTaskStatus:
    async def test_update_to_processing(self, two_cat_migration_svc, init_db, task_factory):
        task = await task_factory(status=TaskStatus.PENDING)

        await two_cat_migration_svc._update_task_status(task, TaskStatus.PROCESSING)
        refreshed = await MigrationTaskModel.get(task.id)
        assert refreshed.status == TaskStatus.PROCESSING
        assert refreshed.completed_at is None

    async def test_update_to_terminal_sets_completed_at(
        self, two_cat_migration_svc, init_db, task_factory,
    ):
        task = await task_factory(status=TaskStatus.PROCESSING)

        await two_cat_migration_svc._update_task_status(task, TaskStatus.COMPLETED)
        refreshed = await MigrationTaskModel.get(task.id)
        assert refreshed.status == TaskStatus.COMPLETED
        assert refreshed.completed_at is not None

    async def test_update_with_extra_fields(
        self, two_cat_migration_svc, init_db, task_factory,
    ):
        task = await task_factory(status=TaskStatus.PROCESSING)

        await two_cat_migration_svc._update_task_status(
            task, TaskStatus.FAILED,
            error_message="boom", failed_step="PROCESSING",
        )
        refreshed = await MigrationTaskModel.get(task.id)
        assert refreshed.error_message == "boom"
        assert refreshed.failed_step == "PROCESSING"


# =======================================================================
# _generate_unique_name
# =======================================================================

class TestGenerateUniqueName:
    def test_generates_counter_1(self, two_cat_migration_svc, two_cat_handler_service, target_dir):
        handler = two_cat_handler_service.get_handler("Target-category")
        target_fs = str(target_dir).replace("\\", "/")

        result = MigrationService._generate_unique_name(handler, target_fs, "video.mp4")
        assert "video(1).mp4" in result

    def test_skips_existing_counter(self, two_cat_migration_svc, two_cat_handler_service, target_dir):
        handler = two_cat_handler_service.get_handler("Target-category")
        target_fs = str(target_dir).replace("\\", "/")

        (target_dir / "video(1).mp4").write_bytes(b"x")

        result = MigrationService._generate_unique_name(handler, target_fs, "video.mp4")
        assert "video(2).mp4" in result

    def test_file_without_extension(self, two_cat_migration_svc, two_cat_handler_service, target_dir):
        handler = two_cat_handler_service.get_handler("Target-category")
        target_fs = str(target_dir).replace("\\", "/")

        result = MigrationService._generate_unique_name(handler, target_fs, "noext")
        assert "noext(1)" in result
        assert "." not in result.rsplit("/", 1)[-1] or result.endswith("(1)")


# =======================================================================
# _cleanup_target
# =======================================================================

class TestCleanupTarget:
    def test_cleanup_existing_file(self, two_cat_migration_svc, two_cat_handler_service, target_dir):
        handler = two_cat_handler_service.get_handler("Target-category")
        target_file = target_dir / "to_clean.mp4"
        target_file.write_bytes(b"data")
        target_fs = str(target_file).replace("\\", "/")

        MigrationService._cleanup_target(handler, target_fs)
        assert not target_file.exists()

    def test_cleanup_nonexistent_file_is_noop(self, two_cat_migration_svc, two_cat_handler_service):
        handler = two_cat_handler_service.get_handler("Target-category")
        MigrationService._cleanup_target(handler, "Z:/nonexistent/file.mp4")
