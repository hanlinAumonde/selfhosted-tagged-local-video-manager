"""Building batches and their children directly in the database, and watching which
directories get refreshed. Shared by the batch service tests and the worker tests."""

import time

from src.features.migration.migration_batch_model import MigrationBatchModel
from src.features.migration.migration_service import MigrationService
from src.features.migration.migration_task_model import MigrationTaskModel
from src.platform.jobs.task_model import TaskStatus


SOURCE_ROOT = "Test-category/Test-resource"
TARGET_ROOT = "Target-category/Target-resource"


async def make_batch(target_dir: str = TARGET_ROOT, conflict_strategy: str | None = None) -> MigrationBatchModel:
    batch = MigrationBatchModel(
        target_dir=target_dir,
        target_category=target_dir.split("/", 1)[0],
        conflict_strategy=conflict_strategy,
        created_at=time.time(),
    )
    await batch.insert()
    return batch


async def add_child(
    task_factory,
    batch: MigrationBatchModel,
    name: str,
    status: TaskStatus = TaskStatus.PENDING,
    sub_dir: str = "",
    **fields,
) -> MigrationTaskModel:
    """A child moving ``{SOURCE_ROOT}/{sub_dir}{name}.mp4`` into the batch's target dir."""
    return await task_factory(
        source_path=f"{SOURCE_ROOT}/{sub_dir}{name}.mp4",
        target_path=f"{batch.target_dir}/{name}.mp4",
        target_category=batch.target_category,
        file_name=name,
        status=status,
        batch_id=batch.id,
        **fields,
    )


def record_directory_refreshes(service: MigrationService) -> list[tuple[str, str]]:
    """Wrap the service's directory refresh so each call is recorded as
    ``(category, DB path)`` and then still performed."""
    calls: list[tuple[str, str]] = []
    dir_meta = service.dirMetadataService
    refresh = dir_meta.update_directory_metadata_forward

    async def recording(directory_path):
        calls.append((directory_path.category, directory_path.DB_format_path()))
        await refresh(directory_path)

    dir_meta.update_directory_metadata_forward = recording
    return calls
