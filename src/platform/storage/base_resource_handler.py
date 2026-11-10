from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator, ClassVar

from src.platform.storage.file_info import FileInfo

if TYPE_CHECKING:
    from src.config import HandlerConfig, Settings


@dataclass(frozen=True)
class HandlerBuildSpec:
    """Everything a handler may need in order to build itself.

    Handlers draw on different things -- the local one wants the process-wide
    ``ROOT_PATH``, an object-storage one wants its own per-mount credentials --
    so the factory hands each of them the same envelope instead of knowing a
    constructor signature per type.
    """

    category: str
    pseudo_paths: dict[str, str]
    config: HandlerConfig
    settings: Settings


class BaseResourceHandler(ABC):
    """Abstract base class for resource IO operations and path conversion."""

    #: The name this backend is declared as in ``handler_config``. It is also the
    #: key the registry files this class under; the two must not drift apart.
    storage_type: ClassVar[str]

    #: Whether a streaming write that fails or is abandoned leaves the path as it found it.
    writes_atomically: ClassVar[bool] = False

    #: Whether a file can reach another path on this storage with no bytes rewritten.
    moves_without_copying: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    def from_config(cls, spec: HandlerBuildSpec) -> BaseResourceHandler:
        """Build a handler for one category from its configuration."""
        ...

    # --- IO operations ---

    @abstractmethod
    async def list_directory(self, path: str) -> list[FileInfo]:
        """
        List the entries of one directory, with every field already read.

        :param path: FS-format path of the directory to list.
        :type path: str
        :return: One FileInfo per entry, directories included.
        :rtype: list[FileInfo]
        :raises FileNotFoundError: If there is no such directory.
        """
        ...

    @abstractmethod
    async def walk(self, path: str) -> AsyncIterator[list[FileInfo]]:
        """
        Every file and directory below ``path``, in batches.

        Batches are the storage's natural unit — a directory for local storage, a listing
        page for S3 — so a caller can check for cancellation or report progress between
        them without paying a thread hop per file. Directories are reported too: an empty
        one leaves no other trace, and a caller aggregating per directory must still see it.

        :param path: FS-format path of the directory to walk.
        :type path: str
        :return: An async iterator of batches of FileInfo.
        :rtype: AsyncIterator[list[FileInfo]]
        :raises FileNotFoundError: If there is no such directory.
        """
        raise NotImplementedError
        yield  # Makes this an async generator, like every override.

    @abstractmethod
    async def stat(self, path: str) -> FileInfo | None:
        """
        Existence, size, mtime and type of one path, in a single round-trip.

        :param path: FS-format path of the file or directory.
        :type path: str
        :return: The FileInfo, or None if nothing is at that path.
        :rtype: FileInfo | None
        """
        ...

    @abstractmethod
    async def delete_file(self, path: str) -> None:
        """
        Delete the file at the given path.

        :param path: The path to the file.
        :type path: str
        """
        ...

    @abstractmethod
    async def create_directory(self, path: str) -> None:
        """
        Create a directory at the given path.

        Refusing an occupied path is part of the contract rather than a convenience: the
        caller reports it as a name already taken, and must never end up adopting a
        directory — or a file — that something else put there.

        :param path: FS-format path of the directory to create.
        :type path: str
        :rtype: None
        :raises FileExistsError: If anything already occupies that path.
        """
        ...

    @abstractmethod
    async def delete_directory(self, path: str) -> None:
        """
        Remove the directory at the given path, which must hold nothing.

        Deliberately narrow: it never recurses. The caller decides whether a directory
        is empty enough to go — usually by asking ``is_directory_empty`` first — so a
        wrong decision upstream costs one refusal rather than a deleted tree.

        :param path: FS-format path of the directory to remove.
        :type path: str
        :rtype: None
        :raises OSError: If the path is not an empty directory.
        """
        ...

    @abstractmethod
    async def is_directory_empty(self, path: str) -> bool:
        """
        Whether the directory holds nothing at all — no files, no sub-directories.

        A storage question rather than a service one: an empty local directory lists
        nothing, while an empty S3 "directory" lists the one marker object standing in
        for it.

        :param path: FS-format path of the directory.
        :type path: str
        :return: True if nothing is left inside.
        :rtype: bool
        """
        ...

    # --- File content read/write ---

    @abstractmethod
    async def read_file_chunk(self, path: str, offset: int, length: int) -> bytes:
        """
        Read a chunk of file data from [offset, offset+length).

        :param path: FS-format path (filesystem path for LocalFS, object key for S3)
        :type path: str
        :param offset: Starting byte offset
        :type offset: int
        :param length: Number of bytes to read
        :type length: int
        :return: The bytes read
        :rtype: bytes
        """
        ...

    @abstractmethod
    async def read_file(self, path: str) -> bytes | None:
        """
        Read a whole small file (a thumbnail, say) in one round-trip.

        :param path: FS-format path
        :type path: str
        :return: The content, or None if there is no such file.
        :rtype: bytes | None
        """
        ...

    async def read_file_streaming(self, path: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        """
        Read a file in a streaming manner, yielding chunks of data.

        :param path: FS-format path (filesystem path for LocalFS, object key for S3)
        :type path: str
        :param chunk_size: Size of each chunk to read (default: 1MB)
        :type chunk_size: int
        :yield: Chunks of file data as bytes
        :rtype: AsyncIterator[bytes]
        """
        info = await self.stat(path)
        if info is None:
            raise FileNotFoundError(path)
        total_size = info.size
        offset = 0
        while offset < total_size:
            length = min(chunk_size, total_size - offset)
            chunk = await self.read_file_chunk(path, offset, length)
            yield chunk
            offset += len(chunk)

    @abstractmethod
    async def write_file(self, path: str, data: bytes) -> None:
        """
        Write a complete file (for small files like thumbnails).

        :param path: FS-format path
        :type path: str
        :param data: File content bytes
        :type data: bytes
        """
        ...

    @abstractmethod
    async def write_file_streaming(self, path: str, data_iterator: AsyncIterator[bytes]) -> int:
        """
        Write a file in a streaming manner (for large files like videos).

        :param path: FS-format path
        :type path: str
        :param data_iterator: An async iterator yielding bytes to write
        :type data_iterator: AsyncIterator[bytes]
        :return: Total number of bytes written
        :rtype: int
        """
        ...

    async def link_file(self, source: str, target: str) -> bool:
        """
        Give a stored file a second path without copying it, if the storage can.

        :param source: FS-format path of the existing file.
        :type source: str
        :param target: FS-format path to add. Must be free.
        :type target: str
        :return: True if the file now has both paths. False leaves the storage unchanged,
            and the caller has to copy instead.
        :rtype: bool
        """
        return False

    async def can_rename(self, source: str, target: str) -> bool:
        """
        Whether a file in ``source``'s directory could be renamed into ``target``'s.

        Answered by trying it on an empty file: only the operating system knows, since
        two bind mounts can look like one filesystem and still refuse.

        :param source: FS-format path of the file that would move.
        :type source: str
        :param target: FS-format path it would end up at.
        :type target: str
        :return: True if the rename would work. Either way ``source`` is left untouched.
        :rtype: bool
        """
        return False

    async def replace_file(self, staged: str, target: str) -> None:
        """
        Atomically move a file onto ``target``, replacing anything already there.

        Only called on storage whose writes are not atomic, since that is the only kind
        that needs to stage a file first or can rename one.

        :param staged: FS-format path of the file to move.
        :type staged: str
        :param target: FS-format path it ends up at.
        :type target: str
        :rtype: None
        """
        raise NotImplementedError(f"{type(self).__name__} cannot replace a staged file")

    async def get_available_space(self, path: str) -> int | None:
        """
        Get the available space at the given path. Returns None if not applicable.

        :param path: The path to check for available space.
        :type path: str
        :return: Available space in bytes, or None if not applicable.
        :rtype: int | None
        """
        return None

    # --- Path resolution ---

    @abstractmethod
    def resolve_path(self, category: str, pseudo_name: str | None, sub_path: str | None) -> str:
        """
        Resolve a parsed relative path (from GraphQL request) into the handler's
        internal absolute/logical path representation.

        :param category: Resource category (e.g. "Local-resource", "S3-resource")
        :type category: str
        :param pseudo_name: Pseudo name within category, or None for category-level
        :type pseudo_name: str | None
        :param sub_path: Remaining sub-path after pseudo_name, or None
        :type sub_path: str | None
        :return: Resolved path in the handler's native format
        :rtype: str
        """
        ...

    # --- Path conversion ---

    @abstractmethod
    def convert_to_DB_format_path(self, path: str) -> str:
        """
        Convert a filesystem-access path to the DB storage format.

        :param path: The filesystem-access path.
        :type path: str
        :return: The DB storage format path.
        :rtype: str
        """
        ...

    @abstractmethod
    def convert_to_FS_format_path(self, path: str) -> str:
        """
        Convert a DB storage path to the filesystem-access format.

        :param path: The DB storage format path.
        :type path: str
        :return: The filesystem-access format path.
        :rtype: str
        """
        ...

    @abstractmethod
    def get_path_standard_format(self, path: str) -> str:
        """
        Normalize path to standard format (forward slashes).

        :param path: The path to normalize.
        :type path: str
        :return: The normalized path.
        :rtype: str
        """
        ...

    # --- External tool access ---

    def get_ffmpeg_accessible_path(self, path: str) -> str | None:
        """
        Return a path/URL that ffmpeg can use as -i input.
        Local handlers return the filesystem path; S3 handlers return a pre-signed URL.
        Returns None if the handler cannot provide direct access (pipe stdin will be used as fallback).

        :param path: The internal path to the video file.
        :type path: str
        :return: A path or URL that ffmpeg can use to access the file, or None if direct access is not available.
        :rtype: str | None
        """
        return None

    # --- File utilities (static) ---

    @staticmethod
    @abstractmethod
    def is_video_file(filename: str) -> bool:
        """
        Check if a file is a video based on its extension.

        :param filename: The name of the file.
        :type filename: str
        :return: True if the file is a video, False otherwise.
        :rtype: bool
        """
        ...

    @staticmethod
    @abstractmethod
    def get_file_extension(filename: str) -> str:
        """
        Get the file extension from a filename.

        :param filename: The name of the file.
        :type filename: str
        :return: The file extension.
        :rtype: str
        """
        ...

    @staticmethod
    @abstractmethod
    def get_filename_without_extension(filename: str) -> str:
        """
        Get the file name without its extension.

        :param filename: The name of the file.
        :type filename: str
        :return: The file name without the extension.
        :rtype: str
        """
        ...

    @staticmethod
    @abstractmethod
    def join_path(*parts: str) -> str:
        """
        Join path parts using the handler's path separator.

        :param parts: The parts of the path to join.
        :type parts: str
        :return: The joined path.
        :rtype: str
        """
        ...

    @staticmethod
    @abstractmethod
    def dirname(path: str) -> str:
        """
        Get the parent directory of a path.

        :param path: The path to get the parent directory of.
        :type path: str
        :return: The parent directory of the path.
        :rtype: str
        """
        ...
