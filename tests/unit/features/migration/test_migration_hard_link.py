"""A migration within one filesystem links the file instead of copying it.

The link stands in for the copy phase only: the source keeps its name until the third
phase, so cancelling, retrying or recovering can still discard the target safely.
"""

import asyncio
import errno
import os

import pytest
from beanie.operators import Set

from src import config
from src.config import Settings
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.features.catalog.series_service import SeriesService
from src.features.catalog.video import VideoModel
from src.features.migration.device_slots import DeviceSlots, device_of
from src.features.migration.migration_service import MigrationService
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus
from src.platform.cache.cache_service import CacheService
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit

SOURCE_DB = "Test-category/Test-resource/movie_a.mp4"
SHELF_DB = "Test-category/Test-resource/shelf/movie_a.mp4"
CONTENT = b"a" * 100  # what local_resource_dir puts in movie_a.mp4


async def _drain(gen) -> None:
    async for _ in gen:
        pass


@pytest.fixture
def no_renames(monkeypatch) -> None:
    """Two paths on different filesystems, which refuse a rename as well as a link."""

    def refuse(src, dst, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "rename", refuse)


class TestLinkingInsteadOfCopying:
    # Scenario: a migration inside one mount does not rewrite the file
    #   Given a video "movie_a.mp4" and a sub-directory on the same mount
    #   When its migration into the sub-directory runs to the end
    #   Then the stored status is COMPLETED
    #   And the target file has the inode the source had
    #   And the source file no longer exists
    #   And the video record points at the target path
    #   And the stored bytes_transferred equals the file size
    async def test_a_migration_inside_one_mount_does_not_rewrite_the_file(
        self, two_cat_migration_svc, shelving_task, local_resource_dir, shelf,
    ):
        source_inode = (local_resource_dir / "movie_a.mp4").stat().st_ino

        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        stored = await MigrationTaskModel.get(shelving_task.id)
        assert stored.status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").stat().st_ino == source_inode
        assert not (local_resource_dir / "movie_a.mp4").exists()
        assert await VideoModel.find_one(VideoModel.path == SHELF_DB) is not None
        assert stored.bytes_transferred == 100

    # Scenario: a migration between categories is never linked
    #   Given a video in "Test-category" and a target directory in "Target-category"
    #   When its migration runs to the end
    #   Then the stored status is COMPLETED
    #   And the target file has a different inode from the one the source had
    async def test_a_migration_between_categories_is_copied(
        self, two_cat_migration_svc, video_factory, task_factory, local_resource_dir, target_dir,
    ):
        await video_factory(name="movie_a", path=SOURCE_DB)
        task = await task_factory(source_path=SOURCE_DB)
        source_inode = (local_resource_dir / "movie_a.mp4").stat().st_ino

        await _drain(two_cat_migration_svc.run_task(str(task.id)))

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.COMPLETED
        assert (target_dir / "movie_a.mp4").stat().st_ino != source_inode

    # Scenario: a filesystem that refuses both the link and the rename falls back to copying
    #   Given a video and a sub-directory on the same mount
    #   And the filesystem rejects hard links and renames
    #   When its migration runs to the end
    #   Then the stored status is COMPLETED
    #   And the target file holds the source's content
    #   And the source file no longer exists
    async def test_a_refused_link_and_rename_fall_back_to_copying(
        self, two_cat_migration_svc, shelving_task, local_resource_dir, shelf,
        no_hard_links, no_renames,
    ):
        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").read_bytes() == CONTENT
        assert not (local_resource_dir / "movie_a.mp4").exists()


class TestTheSourceSurvivesUntilTheLastPhase:
    # Scenario: a cancel accepted right after the link undoes it
    #   Given a video and a sub-directory on the same mount
    #   And the web process raises cancel_requested right after the link is made
    #   When the worker runs the task to the end
    #   Then the stored status is CANCELLED
    #   And the target file does not exist
    #   And the source file still holds its content
    #   And the video record still points at the source path
    async def test_a_cancel_accepted_after_the_link_keeps_the_source(
        self, two_cat_migration_svc, two_cat_handler_service, shelving_task,
        local_resource_dir, shelf, monkeypatch,
    ):
        handler = two_cat_handler_service.get_handler("Test-category")
        link_file = handler.link_file

        async def link_then_cancel(source, target):
            linked = await link_file(source, target)
            await MigrationTaskModel.find_one(MigrationTaskModel.id == shelving_task.id).update(
                Set({MigrationTaskModel.cancel_requested: True})
            )
            return linked

        monkeypatch.setattr(handler, "link_file", link_then_cancel)

        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.CANCELLED
        assert not (shelf / "movie_a.mp4").exists()
        assert (local_resource_dir / "movie_a.mp4").read_bytes() == CONTENT
        assert await VideoModel.find_one(VideoModel.path == SOURCE_DB) is not None

    # Scenario: a worker that dies right after linking loses nothing
    #   Given a task stored as PROCESSING whose target is already a link to the source
    #   When recovery plans the task and the worker runs it
    #   Then the stored status is COMPLETED
    #   And the target file holds the source's content
    #   And the source file no longer exists
    async def test_a_crash_right_after_linking_loses_nothing(
        self, two_cat_migration_svc, shelving_task, local_resource_dir, shelf,
    ):
        await shelving_task.set({MigrationTaskModel.status: TaskStatus.PROCESSING})
        os.link(local_resource_dir / "movie_a.mp4", shelf / "movie_a.mp4")

        await two_cat_migration_svc.plan_recovery()
        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").read_bytes() == CONTENT
        assert not (local_resource_dir / "movie_a.mp4").exists()


    # Scenario: a link that recovery could not remove is not mistaken for a free target
    #   Given a task stored as PROCESSING whose target is already a link to the source
    #   And deleting the target fails, as it does while another process has the file open
    #   When recovery plans the task and the worker runs it
    #   Then the stored status is COMPLETED
    #   And the target file still holds the source's content
    async def test_a_link_recovery_could_not_remove_does_not_empty_the_file(
        self, two_cat_migration_svc, two_cat_handler_service, shelving_task,
        local_resource_dir, shelf, monkeypatch,
    ):
        await shelving_task.set({MigrationTaskModel.status: TaskStatus.PROCESSING})
        os.link(local_resource_dir / "movie_a.mp4", shelf / "movie_a.mp4")

        handler = two_cat_handler_service.get_handler("Test-category")
        delete_file = handler.delete_file

        async def refuse_to_delete_the_target(path):
            if "/shelf/" in path:
                raise PermissionError(13, "The process cannot access the file")
            await delete_file(path)

        monkeypatch.setattr(handler, "delete_file", refuse_to_delete_the_target)

        await two_cat_migration_svc.plan_recovery()
        await _drain(two_cat_migration_svc.run_task(str(shelving_task.id)))

        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED
        assert (shelf / "movie_a.mp4").read_bytes() == CONTENT


def _service(settings: Settings, handler_service: ResourceHandlerService) -> MigrationService:
    return MigrationService(
        resource_handler_service=handler_service,
        dir_metadata_service=DirMetadataService(
            settings=settings,
            resource_handler_service=handler_service,
            cache_service=CacheService(config=settings.cache_config),
        ),
        series_service=SeriesService(),
        copy_slots=DeviceSlots.from_settings(settings),
    )


def _settings_with(test_settings: Settings, monkeypatch, **overrides) -> Settings:
    settings = Settings.model_validate({**test_settings.model_dump(), **overrides})
    monkeypatch.setattr(config, "_settings", settings)
    return settings


async def _stop(run: asyncio.Task) -> None:
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)


class TestDeviceSlots:
    # Scenario: a link does not queue behind a busy device
    #   Given every slot of the mount's device is held by a running copy
    #   And a video and a sub-directory on that mount
    #   When its migration runs
    #   Then it reaches COMPLETED while the slot is still held
    async def test_a_link_on_one_device_does_not_wait_for_a_busy_device(
        self, slotted_migration_svc, two_category_settings, shelving_task,
    ):
        svc = slotted_migration_svc
        device = device_of(two_category_settings, "Test-category", "Test-resource")

        async with svc.copy_slots.hold([device]):
            await asyncio.wait_for(_drain(svc.run_task(str(shelving_task.id))), timeout=5)

            assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED

    # Scenario: falling back to copying takes the slots the fast paths skipped
    #   Given every slot of the mount's device is held by a running copy
    #   And the filesystem rejects hard links and renames
    #   And a video and a sub-directory on that mount
    #   When its migration runs
    #   Then the target file is not written while the slot is held
    #   And once the slot is released the stored status becomes COMPLETED
    async def test_a_refused_link_and_rename_wait_for_the_device_before_copying(
        self, slotted_migration_svc, two_category_settings, shelving_task, shelf,
        no_hard_links, no_renames,
    ):
        svc = slotted_migration_svc
        device = device_of(two_category_settings, "Test-category", "Test-resource")

        async with svc.copy_slots.hold([device]):
            run = asyncio.create_task(_drain(svc.run_task(str(shelving_task.id))))
            await asyncio.sleep(0.2)

            assert not (shelf / "movie_a.mp4").exists()

        await asyncio.wait_for(run, timeout=5)
        assert (await MigrationTaskModel.get(shelving_task.id)).status == TaskStatus.COMPLETED

    # Scenario: two different devices still have to wait
    #   Given two mounts of one category declared as devices "disk-a" and "disk-b"
    #   And every slot of "disk-b" is held by a running copy
    #   When a migration from the first mount to the second runs
    #   Then the stored status stays PENDING while the slot is held
    async def test_a_migration_between_devices_still_waits_for_its_slot(
        self, test_settings, local_resource_dir, target_dir, video_factory, task_factory, monkeypatch,
    ):
        settings = _settings_with(
            test_settings, monkeypatch,
            resource_paths={"Test-category": {
                "Test-resource": str(local_resource_dir),
                "Other-resource": str(target_dir),
            }},
            tasks={"devices": {
                "Test-category/Test-resource": "disk-a",
                "Test-category/Other-resource": "disk-b",
            }},
        )
        svc = _service(settings, ResourceHandlerService(settings=settings))
        await video_factory(name="movie_a", path=SOURCE_DB)
        task = await task_factory(
            source_path=SOURCE_DB,
            target_path="Test-category/Other-resource/movie_a.mp4",
            target_category="Test-category",
        )
        device = device_of(settings, "Test-category", "Other-resource")

        async with svc.copy_slots.hold([device]):
            run = asyncio.create_task(_drain(svc.run_task(str(task.id))))
            await asyncio.sleep(0.2)

            assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.PENDING
            await _stop(run)

    # Scenario: object storage has no link, so it still has to wait
    #   Given an S3 mount whose device has every slot held by a running copy
    #   When a migration between two directories of that mount runs
    #   Then the stored status stays PENDING while the slot is held
    async def test_a_migration_inside_one_bucket_still_waits_for_its_slot(
        self, test_settings, video_factory, task_factory, monkeypatch,
    ):
        settings = _settings_with(
            test_settings, monkeypatch,
            resource_paths={"S3-category": {"R1": "/"}},
            handler_config={"S3-category": {"type": "s3", "mounts": {"R1": {
                "endpoint_url": "http://s3:9000", "access_key": "k", "secret_key": "s", "bucket": "videos",
            }}}},
            tasks={"slots_per_device": {"s3": 1}},
        )
        svc = _service(settings, ResourceHandlerService(settings=settings))
        source_db = "S3-category/R1/movie_a.mp4"
        await video_factory(name="movie_a", path=source_db, category="S3-category")
        task = await task_factory(
            source_path=source_db, source_category="S3-category",
            target_path="S3-category/R1/shelf/movie_a.mp4", target_category="S3-category",
        )
        device = device_of(settings, "S3-category", "R1")

        async with svc.copy_slots.hold([device]):
            run = asyncio.create_task(_drain(svc.run_task(str(task.id))))
            await asyncio.sleep(0.2)

            assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.PENDING
            await _stop(run)
