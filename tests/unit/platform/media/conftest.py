

import asyncio
from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

class _MockProcess:
    """Minimal mock of an asyncio subprocess process.

    Configurable per-test via the constructor.
    """

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        stdout_chunks: list[bytes] | None = None,
    ):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

        # Streaming stdout for transcode tests.
        chunks = list(stdout_chunks or [])
        chunks.append(b"")  # EOF marker

        async def _read(_n: int = -1) -> bytes:
            return chunks.pop(0) if chunks else b""

        self.stdout = MagicMock()
        self.stdout.read = _read

        async def _stderr_read(_n: int = -1) -> bytes:
            return self._stderr

        self.stderr = MagicMock()
        self.stderr.read = _stderr_read

        self.stdin = AsyncMock()
        self.stdin.drain = AsyncMock()
        self.stdin.close = MagicMock()
        self.stdin.write = MagicMock()

        self._wait_called = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    async def wait(self) -> int:
        self._wait_called = True
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


@pytest.fixture
def queue_subprocess(monkeypatch):
    """
    Patch `asyncio.create_subprocess_exec` with a per-test FIFO of mocks.

    Tests append mock processes to the returned deque; the next call to
    `create_subprocess_exec` consumes the front of the queue.
    """
    procs: deque[_MockProcess] = deque()
    captured_calls: list[tuple] = []

    async def _factory(*args, **kwargs):
        captured_calls.append((args, kwargs))
        if not procs:
            raise AssertionError("no mock subprocess queued for this call")
        return procs.popleft()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _factory)
    return procs, captured_calls


@pytest.fixture
def handler_with_direct_path() -> MagicMock:
    h = MagicMock(name="handler")
    h.get_ffmpeg_accessible_path.return_value = "/some/video.mp4"
    return h


@pytest.fixture
def handler_with_piped_only() -> MagicMock:
    """A handler that has no direct ffmpeg path (forces piped mode)."""
    h = MagicMock(name="handler")
    h.get_ffmpeg_accessible_path.return_value = None
    h.get_size.return_value = 100
    h.read_file_chunk = AsyncMock(return_value=b"x" * 100)
    return h
