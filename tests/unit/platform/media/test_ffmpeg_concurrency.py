"""FFmpegService — the configured limit caps how many ffmpeg processes run at once."""

import asyncio
import os

import pytest

from src.platform.media.ffmpeg_service import FFmpegService

pytestmark = pytest.mark.unit


class _HeldProcess:
    """An ffmpeg process that keeps running until the test releases it."""

    returncode = 0

    def __init__(self, release: asyncio.Event):
        self._release = release

    async def communicate(self) -> tuple[bytes, bytes]:
        await self._release.wait()
        return b"JPEG", b""


@pytest.fixture
def held_ffmpeg(monkeypatch) -> tuple[list[tuple], asyncio.Event]:
    started: list[tuple] = []
    release = asyncio.Event()

    async def _start(*args, **kwargs):
        started.append(args)
        return _HeldProcess(release)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _start)
    return started, release


async def _let_waiting_tasks_run() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def test_no_more_processes_run_at_once_than_the_configured_limit(
    held_ffmpeg, handler_with_direct_path, monkeypatch,
):
    # Given an FFmpegService configured with a limit of 2
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    svc = FFmpegService(semaphore_limit=2)
    # And ffmpeg processes that stay running until released
    started, release = held_ffmpeg

    # When 5 thumbnails are requested at the same time
    requests = [
        asyncio.create_task(svc.generate_thumbnail(handler_with_direct_path, f"/v{i}.mp4"))
        for i in range(5)
    ]
    await _let_waiting_tasks_run()

    # Then only 2 ffmpeg processes have been started
    assert len(started) == 2

    # When the running processes are released
    release.set()

    # Then all 5 thumbnails are eventually produced
    assert await asyncio.gather(*requests) == [b"JPEG"] * 5


async def test_limit_above_half_the_cpu_count_is_capped(
    held_ffmpeg, handler_with_direct_path, monkeypatch,
):
    # Given a machine reporting 4 CPUs
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    # And an FFmpegService configured with a limit of 16
    svc = FFmpegService(semaphore_limit=16)
    # And ffmpeg processes that stay running until released
    started, release = held_ffmpeg

    # When 5 thumbnails are requested at the same time
    requests = [
        asyncio.create_task(svc.generate_thumbnail(handler_with_direct_path, f"/v{i}.mp4"))
        for i in range(5)
    ]
    await _let_waiting_tasks_run()

    # Then only 2 ffmpeg processes have been started
    assert len(started) == 2

    release.set()
    await asyncio.gather(*requests)
