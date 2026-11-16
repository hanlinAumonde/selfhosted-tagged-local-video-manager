import asyncio
from collections.abc import Iterable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator

from src.config import S3CategoryConfig, Settings


@dataclass(frozen=True)
class Device:
    """
    A piece of storage that copies compete for: a disk, or an S3 bucket.

    :param name: Identity of the device; mounts with the same name share its slots.
    :param limit: Copies allowed on it at once.
    """

    name: str
    limit: int


def device_of(settings: Settings, category: str, pseudo_name: str) -> Device:
    """
    Work out which device a mount lives on.

    A declaration in ``tasks.devices`` wins, because several mounts on one physical disk
    look like independent directories to the code. Otherwise a local mount is its own
    device, and S3 mounts on the same endpoint and bucket share one.

    The limit comes from ``tasks.device_limits`` for the resolved name, else from
    ``tasks.slots_per_device`` for the mount's storage type.

    :param settings: Application settings.
    :type settings: Settings
    :param category: Category of the mount.
    :type category: str
    :param pseudo_name: Pseudo name of the mount within the category.
    :type pseudo_name: str
    :return: The device and its limit.
    :rtype: Device
    """
    tasks = settings.tasks
    handler_config = settings.get_handler_config(category)

    name = tasks.devices.get(f"{category}/{pseudo_name}")
    if not name:
        if isinstance(handler_config, S3CategoryConfig):
            mount = handler_config.mounts[pseudo_name]
            name = f"s3:{mount.endpoint_url}/{mount.bucket}"
        else:
            name = f"local:{category}/{pseudo_name}"

    limit = tasks.device_limits.get(name, tasks.slots_per_device.get(handler_config.type, 1))
    return Device(name, limit)


class DeviceSlots:
    """
    Who may copy right now: a cap on copies in total, and a cap per device.

    In-process semaphores are enough only because each queue has exactly one worker
    process; a second migration worker would need these to become distributed locks.
    """

    def __init__(self, global_limit: int, settings: Settings | None = None):
        """
        :param global_limit: Copies allowed at once across every device.
        :type global_limit: int
        :param settings: Used to resolve the devices of a task's paths; only needed by
            ``devices_of``.
        :type settings: Settings | None
        """
        self._global = asyncio.Semaphore(max(1, global_limit))
        self._per_device: dict[str, asyncio.Semaphore] = {}
        self._settings = settings

    @classmethod
    def from_settings(cls, settings: Settings) -> "DeviceSlots":
        return cls(global_limit=settings.tasks.max_concurrent, settings=settings)

    def devices_of(self, *db_paths: str) -> list[Device]:
        """
        The devices the given DB-format paths live on.

        :param db_paths: Paths in ``{category}/{pseudo_name}/...`` form.
        :type db_paths: str
        :return: One device per path, in the same order.
        :rtype: list[Device]
        """
        if self._settings is None:
            raise RuntimeError("DeviceSlots needs settings to resolve devices from paths")
        devices = []
        for path in db_paths:
            category, pseudo_name = path.split("/", 2)[:2]
            devices.append(device_of(self._settings, category, pseudo_name))
        return devices

    @asynccontextmanager
    async def hold(self, devices: Iterable[Device]) -> AsyncGenerator[None, None]:
        """
        Wait for a slot on every given device and a global slot, and hold them.

        Devices are taken in name order, each at most once, so a copy from A to B and one
        from B to A can never each hold half of what the other needs. The global slot is
        taken last: a copy waiting for a busy disk must not sit on a global slot that a
        copy between two idle devices could be using.

        :param devices: The devices the copy reads from and writes to.
        :type devices: Iterable[Device]
        :rtype: AsyncGenerator[None, None]
        """
        unique = sorted({device.name: device for device in devices}.values(), key=lambda d: d.name)
        async with AsyncExitStack() as stack:
            for device in unique:
                await stack.enter_async_context(self._semaphore_for(device))
            await stack.enter_async_context(self._global)
            yield

    def _semaphore_for(self, device: Device) -> asyncio.Semaphore:
        semaphore = self._per_device.get(device.name)
        if semaphore is None:
            semaphore = asyncio.Semaphore(max(1, device.limit))
            self._per_device[device.name] = semaphore
        return semaphore
