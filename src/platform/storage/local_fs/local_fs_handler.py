import asyncio
import os
import shutil
from stat import S_ISDIR
from typing import AsyncIterator

import aiofiles

from src.config import get_settings
from src.logger import get_logger
from src.platform.storage.base_resource_handler import BaseResourceHandler, HandlerBuildSpec
from src.platform.storage.file_info import FileInfo

logger = get_logger("local_fs_handler")


class LocalFSResourceHandler(BaseResourceHandler):
    """Resource handler for local filesystem operations."""

    storage_type = "local_fs"

    @classmethod
    def from_config(cls, spec: HandlerBuildSpec) -> "LocalFSResourceHandler":
        """Mount locations come from ``resource_paths``; the only extra input is
        the container mount base, which is process-wide rather than per category."""
        return cls(spec.category, spec.pseudo_paths, spec.settings.ROOT_PATH)

    def __init__(self, category: str, pseudo_paths: dict[str, str], root_path: str | None):
        """
        :param category: Category name (e.g. "Local-resource")
        :param pseudo_paths: Mapping of pseudo_name -> host_path for this category
        :param root_path: ROOT_PATH env var (container mount base), None for local dev
        """
        self._category = category
        self._pseudo_paths = pseudo_paths
        self._root_path = root_path

    # --- IO operations ---

    def _scan(self, path: str) -> list[FileInfo]:
        """List one directory and stat every entry in it, all on the calling thread."""
        infos: list[FileInfo] = []
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    is_dir = entry.is_dir()
                    entry_stat = entry.stat()
                except OSError as e:
                    # Gone between the listing and the stat, or unreadable: the rest of
                    # the directory is still worth reporting.
                    logger.warning(f"Skipping unreadable entry {entry.path}: {e}")
                    continue
                infos.append(FileInfo(
                    name=entry.name,
                    path=self.get_path_standard_format(entry.path),
                    is_dir=is_dir,
                    size=0.0 if is_dir else entry_stat.st_size,
                    mtime=entry_stat.st_mtime,
                ))
        return infos

    async def list_directory(self, path: str) -> list[FileInfo]:
        return await asyncio.to_thread(self._scan, path)

    async def walk(self, path: str) -> AsyncIterator[list[FileInfo]]:
        """One batch per directory. Only the root failing is an error: an unreadable
        sub-directory is logged and skipped, so one bad folder does not hide a tree."""
        pending = [path]
        while pending:
            current = pending.pop()
            try:
                batch = await asyncio.to_thread(self._scan, current)
            except OSError as e:
                if current is path:
                    raise
                logger.warning(f"Skipping unreadable directory {current}: {e}")
                continue
            pending.extend(info.path for info in batch if info.is_dir)
            if batch:
                yield batch

    def _stat(self, path: str) -> FileInfo | None:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        is_dir = S_ISDIR(st.st_mode)
        standard = self.get_path_standard_format(path)
        return FileInfo(
            name=standard.rsplit("/", 1)[-1],
            path=standard,
            is_dir=is_dir,
            size=0.0 if is_dir else st.st_size,
            mtime=st.st_mtime,
        )

    async def stat(self, path: str) -> FileInfo | None:
        return await asyncio.to_thread(self._stat, path)

    async def delete_file(self, path: str) -> None:
        await asyncio.to_thread(os.remove, path)

    async def create_directory(self, path: str) -> None:
        """``os.makedirs`` already raises FileExistsError for an occupied path, file included."""
        await asyncio.to_thread(os.makedirs, path)

    async def delete_directory(self, path: str) -> None:
        """``os.rmdir`` already refuses anything but an empty directory."""
        await asyncio.to_thread(os.rmdir, path)

    async def is_directory_empty(self, path: str) -> bool:
        def _is_empty() -> bool:
            with os.scandir(path) as entries:
                return next(entries, None) is None

        return await asyncio.to_thread(_is_empty)

    # --- File content read/write ---

    async def read_file(self, path: str) -> bytes | None:
        try:
            async with aiofiles.open(path, "rb") as f:
                return await f.read()
        except FileNotFoundError:
            return None

    async def read_file_chunk(self, path: str, offset: int, length: int) -> bytes:
        async with aiofiles.open(path, "rb") as f:
            await f.seek(offset)
            return await f.read(length)

    async def write_file(self, path: str, data: bytes) -> None:
        await asyncio.to_thread(os.makedirs, os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)

    async def write_file_streaming(self, path: str, data_stream: AsyncIterator[bytes]) -> int:
        await asyncio.to_thread(os.makedirs, os.path.dirname(path), exist_ok=True)
        total_written = 0
        async with aiofiles.open(path, "wb") as f:
            async for chunk in data_stream:
                await f.write(chunk)
                total_written += len(chunk)
        return total_written

    async def get_available_space(self, path: str) -> int | None:
        try:
            usage = await asyncio.to_thread(shutil.disk_usage, os.path.dirname(path))
            return usage.free
        except OSError:
            return None

    # --- Path resolution ---

    def resolve_path(self, category: str, pseudo_name: str | None, sub_path: str | None) -> str:
        if pseudo_name is None:
            return category

        if self._root_path:
            abs_resource_path = self.join_path(self._root_path, category, pseudo_name)
        else:
            abs_resource_path = self.get_path_standard_format(self._pseudo_paths[pseudo_name])

        if sub_path is None:
            return abs_resource_path
        return self.get_path_standard_format(os.path.join(abs_resource_path, sub_path.lstrip("/")))

    # --- Path conversion ---

    def convert_to_DB_format_path(self, path: str) -> str:
        """
        Convert any path to DB logical format: {category}/{pseudo_name}/{relative}.
        Auto-detects input: if already logical, returns as-is; if FS path, converts.
        """
        path = self.get_path_standard_format(path)

        # Already in logical format
        if path.startswith(self._category + "/"):
            return path

        # FS path → logical path
        if self._root_path:
            for pseudo_name in self._pseudo_paths:
                mounted_root = self.get_path_standard_format(
                    os.path.join(self._root_path, self._category, pseudo_name)
                )
                if path == mounted_root or path.startswith(mounted_root + "/"):
                    relative = path[len(mounted_root):].lstrip("/")
                    if relative:
                        return f"{self._category}/{pseudo_name}/{relative}"
                    return f"{self._category}/{pseudo_name}"
        else:
            for pseudo_name, host_path in self._pseudo_paths.items():
                normalized = self.get_path_standard_format(host_path)
                if path == normalized or path.startswith(normalized + "/"):
                    relative = path[len(normalized):].lstrip("/")
                    if relative:
                        return f"{self._category}/{pseudo_name}/{relative}"
                    return f"{self._category}/{pseudo_name}"

        return path

    def convert_to_FS_format_path(self, path: str) -> str:
        """
        Convert any path to FS-accessible format.
        Auto-detects input: if logical path, converts to FS; if already FS, returns as-is.
        """
        path_std = self.get_path_standard_format(path)

        # Logical path → FS path
        if path_std.startswith(self._category + "/"):
            rest = path_std[len(self._category) + 1:]
            parts = rest.split("/", 1)
            pseudo_name = parts[0]
            relative = parts[1] if len(parts) > 1 else ""

            if pseudo_name in self._pseudo_paths:
                if self._root_path:
                    base = os.path.join(self._root_path, self._category, pseudo_name)
                else:
                    base = self._pseudo_paths[pseudo_name]

                if relative:
                    return self.get_path_standard_format(os.path.join(base, relative))
                return self.get_path_standard_format(base)

        # Already FS path or unknown format
        return self.get_path_standard_format(path)

    def get_path_standard_format(self, path: str) -> str:
        return os.path.normpath(path).replace("\\", "/")

    # --- External tool access ---

    def get_ffmpeg_accessible_path(self, path: str) -> str | None:
        return path

    # --- File utilities (static) ---

    @staticmethod
    def is_video_file(filename: str) -> bool:
        _, ext = os.path.splitext(filename.lower())
        return ext in get_settings().video_extensions
    
    @staticmethod
    def get_file_extension(filename: str) -> str:
        return os.path.splitext(filename)[1][1:]  # Exclude the dot

    @staticmethod
    def get_filename_without_extension(filename: str) -> str:
        return os.path.splitext(os.path.basename(filename))[0]

    @staticmethod
    def join_path(*parts: str) -> str:
        return os.path.normpath(os.path.join(*parts)).replace("\\", "/")

    @staticmethod
    def dirname(path: str) -> str:
        return os.path.dirname(path).replace("\\", "/")
