from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import AsyncIterator, Generator, Iterator

from src.platform.storage.base_file_entry import BaseFileEntry


class BaseResourceHandler(ABC):
    """Abstract base class for resource IO operations and path conversion."""

    # --- IO operations ---

    @abstractmethod
    @contextmanager
    def list_directory(self, path: str) -> Generator[Iterator[BaseFileEntry], None, None]:
        """
        List entries in a directory. Returns a context manager yielding BaseFileEntry iterator.

        :param path: The path to the directory to list.
        :type path: str
        :return: A context manager yielding an iterator of BaseFileEntry objects representing the directory entries.
        :rtype: Generator[Iterator[BaseFileEntry], None, None]
        """
        ...

    @abstractmethod
    def get_entry(self, path: str) -> BaseFileEntry:
        """
        Get a single file/directory entry by its path (not via directory listing).

        :param path: The path to the file or directory.
        :type path: str
        :return: The file or directory entry.
        :rtype: BaseFileEntry
        """
        ...

    @abstractmethod
    def get_size(self, path: str) -> float:
        """
        Get the size of a file at the given path.

        :param path: The path to the file.
        :type path: str
        :return: The size of the file in bytes.
        :rtype: float
        """
        ...

    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """
        Check if a file exists at the given path.

        :param path: The path to the file.
        :type path: str
        :return: True if the file exists, False otherwise.
        :rtype: bool
        """
        ...

    @abstractmethod
    def delete_file(self, path: str) -> None:
        """
        Delete the file at the given path.

        :param path: The path to the file.
        :type path: str
        """
        ...

    @abstractmethod
    def create_directory(self, path: str) -> None:
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
        total_size = self.get_size(path)
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

    def get_available_space(self, path: str) -> int | None:
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
