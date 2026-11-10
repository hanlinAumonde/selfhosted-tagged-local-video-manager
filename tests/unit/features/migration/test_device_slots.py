"""Copy slots for migrations: a global cap plus a cap per storage device.

Two tasks on one spinning disk turn sequential reads into seeks, so the device a copy
touches is limited separately from how many copies run in total.
"""

import asyncio
from contextlib import AsyncExitStack

import pytest

from src.config import Settings
from src.features.migration.device_slots import Device, DeviceSlots, device_of
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus

pytestmark = pytest.mark.unit


def _settings(**overrides) -> Settings:
    payload = {
        "resource_paths": {
            "Local": {"A": "/disk/a", "B": "/disk/b"},
            "S3": {"R1": "/", "R2": "/", "R3": "/"},
        },
        "handler_config": {
            "S3": {
                "type": "s3",
                "mounts": {
                    "R1": {"endpoint_url": "http://s3:9000", "access_key": "k", "secret_key": "s", "bucket": "videos"},
                    "R2": {"endpoint_url": "http://s3:9000", "access_key": "k", "secret_key": "s", "bucket": "videos"},
                    "R3": {"endpoint_url": "http://s3:9000", "access_key": "k", "secret_key": "s", "bucket": "archive"},
                },
            }
        },
    }
    payload.update(overrides)
    return Settings.model_validate(payload)


async def _admitted(slots: DeviceSlots, *requests: list[Device]) -> tuple[int, AsyncExitStack]:
    """Ask for each request concurrently; report how many got in shortly after."""
    stack = AsyncExitStack()
    entered = 0

    async def take(devices):
        nonlocal entered
        await stack.enter_async_context(slots.hold(devices))
        entered += 1

    waiters = [asyncio.create_task(take(devices)) for devices in requests]
    await asyncio.sleep(0.05)
    for waiter in waiters:
        waiter.cancel()
    await asyncio.gather(*waiters, return_exceptions=True)
    return entered, stack


LOCAL = 1
S3 = 2


class TestDeviceOfAMount:
    def test_each_local_mount_is_its_own_device_by_default(self):
        # Given settings with local mounts "Local/A" and "Local/B" and no device declarations
        settings = _settings()

        # When the device of each mount is resolved
        a, b = device_of(settings, "Local", "A"), device_of(settings, "Local", "B")

        # Then the two device names differ
        assert a.name != b.name
        assert a.limit == b.limit == 1

    def test_local_mounts_declared_on_one_disk_share_a_device(self):
        # Given settings declaring both "Local/A" and "Local/B" as device "hdd-1"
        settings = _settings(tasks={"devices": {"Local/A": "hdd-1", "Local/B": "hdd-1"}})

        # When the device of each mount is resolved
        a, b = device_of(settings, "Local", "A"), device_of(settings, "Local", "B")

        # Then both resolve to the same device name
        assert a.name == b.name

    def test_s3_mounts_on_the_same_endpoint_and_bucket_share_a_device(self):
        # Given an S3 category with mounts "R1" and "R2" on the same endpoint and bucket
        # And a mount "R3" on a different bucket
        settings = _settings()

        # When the device of each mount is resolved
        r1, r2, r3 = (device_of(settings, "S3", name) for name in ("R1", "R2", "R3"))

        # Then R1 and R2 resolve to the same device name and R3 to a different one
        assert r1.name == r2.name
        assert r3.name != r1.name
        assert r1.limit == 2


class TestSlots:
    async def test_copies_on_different_devices_run_at_the_same_time(self):
        # Given slots with global limit 4 and 1 slot per local device
        slots = DeviceSlots(global_limit=4)

        # When one holder takes devices ["a", "b"] and another takes ["c", "d"]
        entered, stack = await _admitted(
            slots,
            [Device("a", LOCAL), Device("b", LOCAL)],
            [Device("c", LOCAL), Device("d", LOCAL)],
        )

        # Then both are holding at once
        assert entered == 2
        await stack.aclose()

    async def test_second_copy_on_the_same_local_device_waits(self):
        # Given slots with global limit 4 and 1 slot per local device
        slots = DeviceSlots(global_limit=4)
        # And one holder taking local device "a"
        async with slots.hold([Device("a", LOCAL)]):
            # When a second holder asks for local device "a"
            second = asyncio.create_task(self._hold_once(slots, [Device("a", LOCAL)]))
            await asyncio.sleep(0.05)

            # Then it is not admitted until the first releases
            assert not second.done()
        await asyncio.wait_for(second, timeout=1)

    async def test_an_s3_device_admits_two_copies(self):
        # Given slots with 2 slots per S3 device
        slots = DeviceSlots(global_limit=4)

        # When three holders ask for S3 device "s3"
        entered, stack = await _admitted(slots, *([Device("s3", S3)] for _ in range(3)))

        # Then two are admitted and the third waits
        assert entered == 2
        await stack.aclose()

    async def test_global_limit_caps_copies_across_devices(self):
        # Given slots with global limit 2 and 1 slot per local device
        slots = DeviceSlots(global_limit=2)

        # When three holders ask for distinct local devices "a", "b" and "c"
        entered, stack = await _admitted(
            slots, [Device("a", LOCAL)], [Device("b", LOCAL)], [Device("c", LOCAL)]
        )

        # Then two are admitted and the third waits
        assert entered == 2
        await stack.aclose()

    async def test_same_source_and_target_device_takes_one_slot(self):
        # Given slots with 1 slot per local device
        slots = DeviceSlots(global_limit=4)

        # When a holder asks for ["a", "a"]
        # Then it is admitted without waiting on itself
        await asyncio.wait_for(
            self._hold_once(slots, [Device("a", LOCAL), Device("a", LOCAL)]), timeout=1
        )

    async def test_opposite_direction_copies_do_not_deadlock(self):
        # Given slots with 1 slot per local device
        slots = DeviceSlots(global_limit=4)
        a, b = Device("a", LOCAL), Device("b", LOCAL)

        # When holders for a->b and b->a repeatedly ask at the same time
        async def copy_repeatedly(devices):
            for _ in range(20):
                await self._hold_once(slots, devices)

        # Then every holder is eventually admitted within a timeout
        await asyncio.wait_for(
            asyncio.gather(copy_repeatedly([a, b]), copy_repeatedly([b, a])), timeout=2
        )

    async def test_slots_are_returned_when_the_holder_raises(self):
        # Given slots with 1 slot per local device
        slots = DeviceSlots(global_limit=4)
        # And a holder of "a" that raises inside its slot
        with pytest.raises(RuntimeError):
            async with slots.hold([Device("a", LOCAL)]):
                raise RuntimeError("copy failed")

        # When another holder asks for "a"
        # Then it is admitted immediately
        await asyncio.wait_for(self._hold_once(slots, [Device("a", LOCAL)]), timeout=0.1)

    @staticmethod
    async def _hold_once(slots: DeviceSlots, devices: list[Device]) -> None:
        async with slots.hold(devices):
            await asyncio.sleep(0)


# -----------------------------------------------------------------------
# The migration service holds its devices' slots for the copy phase
# -----------------------------------------------------------------------

async def _drain(gen) -> None:
    async for _ in gen:
        pass


class TestMigrationUsesSlots:
    async def test_migration_waits_as_pending_while_its_target_device_is_busy(
        self, slotted_migration_svc, two_category_settings, init_db,
        video_factory, task_factory,
    ):
        # Given a migration service whose slots allow 1 copy per local device
        svc = slotted_migration_svc
        # And a PENDING migration task from mount A to mount B
        source_db = "Test-category/Test-resource/movie_a.mp4"
        target_db = "Target-category/Target-resource/movie_a.mp4"
        await video_factory(name="movie_a", path=source_db)
        task = await task_factory(source_path=source_db, target_path=target_db, file_size=100)

        # And mount B's device slot already held by someone else
        target_device = device_of(two_category_settings, "Target-category", "Target-resource")
        async with svc.copy_slots.hold([target_device]):
            # When the task is run
            run = asyncio.create_task(_drain(svc.run_task(str(task.id))))
            await asyncio.sleep(0.1)

            # Then the stored status stays PENDING while the slot is held
            assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.PENDING

        # And once the slot is released the task completes
        await asyncio.wait_for(run, timeout=5)
        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.COMPLETED

    async def test_migration_resuming_at_db_update_does_not_wait_for_a_slot(
        self, slotted_migration_svc, two_category_settings, init_db,
        video_factory, task_factory, target_dir,
    ):
        # Given a migration service whose slots allow 1 copy per local device
        svc = slotted_migration_svc
        # And a PENDING migration task with resume_from UPDATING_DB and its target file already copied
        source_db = "Test-category/Test-resource/movie_a.mp4"
        target_db = "Target-category/Target-resource/movie_a.mp4"
        await video_factory(name="movie_a", path=source_db)
        (target_dir / "movie_a.mp4").write_bytes(b"a" * 100)
        task = await task_factory(
            source_path=source_db, target_path=target_db, file_size=100,
            resume_from=TaskStatus.UPDATING_DB,
        )

        # And both devices' slots held by someone else
        devices = [
            device_of(two_category_settings, "Test-category", "Test-resource"),
            device_of(two_category_settings, "Target-category", "Target-resource"),
        ]
        async with svc.copy_slots.hold(devices):
            # When the task is run
            # Then it completes without waiting
            await asyncio.wait_for(_drain(svc.run_task(str(task.id))), timeout=5)

        assert (await MigrationTaskModel.get(task.id)).status == TaskStatus.COMPLETED


class TestDeviceLimits:
    """The storage type only gives a default: a solid-state disk is a ``local_fs`` mount
    like a spinning one, yet takes several copies at once without slowing down."""

    # Scenario: a device listed in device_limits gets that limit
    #   Given settings declaring "Local/A" as device "ssd-1"
    #   And device_limits giving "ssd-1" a limit of 3
    #   When the device of "Local/A" is resolved
    #   Then its name is "ssd-1" and its limit is 3
    def test_listed_device_takes_its_limit_from_device_limits(self):
        settings = _settings(tasks={
            "devices": {"Local/A": "ssd-1"},
            "device_limits": {"ssd-1": 3},
        })

        device = device_of(settings, "Local", "A")

        assert device == Device("ssd-1", 3)

    # Scenario: a device not listed falls back to its storage type's default
    #   Given settings giving device "ssd-1" a limit of 3 in device_limits
    #   And "Local/B" not declared as any device
    #   When the device of "Local/B" is resolved
    #   Then its limit is slots_per_device["local_fs"], i.e. 1
    def test_unlisted_device_falls_back_to_its_storage_type_default(self):
        settings = _settings(tasks={
            "devices": {"Local/A": "ssd-1"},
            "device_limits": {"ssd-1": 3},
        })

        device = device_of(settings, "Local", "B")

        assert device.limit == 1

    # Scenario: device_limits is keyed by the resolved device name, inferred ones included
    #   Given settings with no device declarations
    #   And device_limits giving the inferred S3 device "s3:http://s3:9000/videos" a limit of 5
    #   When the devices of "S3/R1" and "S3/R3" are resolved
    #   Then "S3/R1" has limit 5
    #   And "S3/R3", on bucket "archive", keeps the s3 default of 2
    def test_limit_applies_to_an_inferred_device_name(self):
        settings = _settings(tasks={"device_limits": {"s3:http://s3:9000/videos": 5}})

        videos = device_of(settings, "S3", "R1")
        archive = device_of(settings, "S3", "R3")

        assert videos.limit == 5
        assert archive.limit == S3

    # Scenario: mounts sharing a device always share its limit
    #   Given settings declaring both "Local/A" and "Local/B" as device "ssd-1"
    #   And device_limits giving "ssd-1" a limit of 3
    #   When the devices of both mounts are resolved
    #   Then both have limit 3
    def test_mounts_sharing_a_device_share_its_limit(self):
        settings = _settings(tasks={
            "devices": {"Local/A": "ssd-1", "Local/B": "ssd-1"},
            "device_limits": {"ssd-1": 3},
        })

        a, b = device_of(settings, "Local", "A"), device_of(settings, "Local", "B")

        assert a == b == Device("ssd-1", 3)

    # Scenario: two copies into one solid-state disk run at the same time
    #   Given local mounts "Local/A" as "hdd-1", "Local/B" as "hdd-2" and "Local/C" as "ssd-1"
    #   And device_limits giving "ssd-1" a limit of 2, with a global limit of 4
    #   When copies from "Local/A" into "Local/C" and from "Local/B" into "Local/C" ask for slots at once
    #   Then both are admitted
    #   And a third copy from "Local/A" into "Local/C" still waits, on "hdd-1"
    async def test_two_copies_into_a_device_with_limit_two_run_together(self):
        # Local/C is local_fs on purpose: its type default is 1, so only device_limits
        # can let a second copy in.
        settings = _settings(
            resource_paths={
                "Local": {"A": "/disk/a", "B": "/disk/b", "C": "/disk/c"},
                "S3": {"R1": "/", "R2": "/", "R3": "/"},
            },
            tasks={
                "max_concurrent": 4,
                "devices": {"Local/A": "hdd-1", "Local/B": "hdd-2", "Local/C": "ssd-1"},
                "device_limits": {"ssd-1": 2},
            },
        )
        slots = DeviceSlots.from_settings(settings)
        a_to_c = slots.devices_of("Local/A/x.mp4", "Local/C/x.mp4")
        b_to_c = slots.devices_of("Local/B/y.mp4", "Local/C/y.mp4")

        entered, stack = await _admitted(slots, a_to_c, b_to_c)
        try:
            assert entered == 2
            third, third_stack = await _admitted(slots, a_to_c)
            await third_stack.aclose()
            assert third == 0
        finally:
            await stack.aclose()
