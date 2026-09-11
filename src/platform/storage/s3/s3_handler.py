import posixpath
from contextlib import contextmanager
from typing import AsyncIterator, Generator, Iterator
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from fastapi.concurrency import run_in_threadpool
from src.config import get_settings
from src.config import S3HandlerConfig
from src.platform.storage.base_file_entry import BaseFileEntry
from src.platform.storage.base_resource_handler import BaseResourceHandler
from src.platform.storage.s3.s3_file_entry import S3FileEntry


class S3ResourceHandler(BaseResourceHandler):
    """Resource handler for S3-compatible object storage (MinIO, RustFS, etc.)."""

    # S3 key prefixes for different content types
    VIDEO_PREFIX = "videos"
    THUMBNAIL_PREFIX = "thumbnails"

    def __init__(
        self,
        category: str,
        pseudo_paths: dict[str, str],
        handler_configs: dict[str, S3HandlerConfig],
    ):
        """
        :param category: Category name (e.g. "S3-resource")
        :param pseudo_paths: {pseudo_name: prefix_path} from resource_paths
        :param handler_configs: {pseudo_name: S3HandlerConfig} from handler_config
        """
        self._category = category
        self._pseudo_paths = pseudo_paths
        self._configs = handler_configs
        self._buckets: dict[str, "boto3.resources.factory.s3.Bucket"] = {}

        for pseudo_name, config in handler_configs.items():
            s3 = boto3.resource(
                "s3",
                endpoint_url=config.endpoint_url,
                aws_access_key_id=config.access_key,
                aws_secret_access_key=config.secret_key,
                region_name=config.region or "us-east-1",
                config=Config(
                    signature_version='s3v4',
                    #s3={'addressing_style': 'path'},
                    connect_timeout=5,
                    read_timeout=10,
                    retries={'max_attempts': 3}
                )
            )
            self._buckets[pseudo_name] = s3.Bucket(config.bucket)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_pseudo_name_from_key(self, key: str) -> tuple[str, str]:
        """
        Extract pseudo_name and remaining path from an S3 key.

        Key format: "{prefix}/{pseudo_name}/{relative_path}"
        e.g. "videos/Resource-1/action/movie.mp4" → ("Resource-1", "action/movie.mp4")
        """
        parts = key.split("/", 2)
        if len(parts) < 2:
            raise ValueError(f"Invalid S3 key format: {key}")
        pseudo_name = parts[1]
        relative = parts[2] if len(parts) > 2 else ""
        return pseudo_name, relative

    def _get_bucket(self, pseudo_name: str) -> "boto3.resources.factory.s3.Bucket":
        """Get the Bucket resource for a given pseudo_name."""
        if pseudo_name not in self._buckets:
            raise ValueError(
                f"No S3 client configured for pseudo_name '{pseudo_name}' "
                f"in category '{self._category}'"
            )
        return self._buckets[pseudo_name]

    def _get_object(self, path: str) -> "boto3.resources.factory.s3.Object":
        """Get an S3 Object resource from an S3 key."""
        pseudo_name, _ = self._get_pseudo_name_from_key(path)
        bucket = self._get_bucket(pseudo_name)
        return bucket.Object(path)

    def _build_video_key(self, pseudo_name: str, relative_path: str) -> str:
        """Build S3 key for a video file."""
        return posixpath.join(self.VIDEO_PREFIX, pseudo_name, relative_path)

    def _build_thumbnail_key(self, pseudo_name: str, relative_path: str) -> str:
        """Build S3 key for a thumbnail file."""
        return posixpath.join(self.THUMBNAIL_PREFIX, pseudo_name, relative_path)

    def _parse_logical_path(self, logical_path: str) -> tuple[str, str]:
        """
        Parse a DB logical path into (pseudo_name, relative_path).

        Logical path format: "{category}/{pseudo_name}/{relative_path}"
        e.g. "S3-resource/Resource-1/action/movie.mp4" → ("Resource-1", "action/movie.mp4")
        """
        if logical_path.startswith(self._category + "/"):
            logical_path = logical_path[len(self._category) + 1:]
        parts = logical_path.split("/", 1)
        pseudo_name = parts[0]
        relative = parts[1] if len(parts) > 1 else ""
        return pseudo_name, relative

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def resolve_path(self, category: str, pseudo_name: str | None, sub_path: str | None) -> str:
        if pseudo_name is None:
            return category

        if sub_path is None:
            return f"{category}/{pseudo_name}"
        return f"{category}/{pseudo_name}/{sub_path.lstrip('/')}"

    # ------------------------------------------------------------------
    # IO operations
    # ------------------------------------------------------------------

    @contextmanager
    def list_directory(self, path: str) -> Generator[Iterator[BaseFileEntry], None, None]:
        """
        List entries in a "directory" (S3 prefix).
        path is an S3 key prefix, e.g. "videos/Resource-1/action/"

        Uses the underlying client paginator because Bucket.objects.filter()
        does not expose CommonPrefixes (needed for pseudo-directory listing).
        """
        pseudo_name, _ = self._get_pseudo_name_from_key(path)
        bucket = self._get_bucket(pseudo_name)
        client = bucket.meta.client

        prefix = path if path.endswith("/") else path + "/"

        entries: list[BaseFileEntry] = []
        paginator = client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=bucket.name, Prefix=prefix, Delimiter="/"):
            for cp in page.get("CommonPrefixes", []):
                entries.append(S3FileEntry(key=cp["Prefix"], is_directory=True))

            for obj in page.get("Contents", []):
                if obj["Key"] == prefix:
                    continue
                entries.append(S3FileEntry(
                    key=obj["Key"],
                    size=obj["Size"],
                    mtime=obj["LastModified"].timestamp(),
                    is_directory=False,
                ))

        yield (iter(entries))

    def get_entry(self, path: str) -> BaseFileEntry:
        """Get a single S3 object entry by its key."""
        obj = self._get_object(path)
        try:
            obj.load()
            return S3FileEntry(
                key=path,
                size=obj.content_length,
                mtime=obj.last_modified.timestamp(),
                is_directory=False,
            )
        except ClientError:
            return S3FileEntry(key=path, is_directory=True)

    def get_size(self, path: str) -> float:
        obj = self._get_object(path)
        obj.load()
        return obj.content_length

    def file_exists(self, path: str) -> bool:
        obj = self._get_object(path)
        try:
            obj.load()
            return True
        except ClientError:
            return False

    def delete_file(self, path: str) -> None:
        self._get_object(path).delete()

    def create_directory(self, path: str) -> None:
        """
        Object storage has no directories, so one zero-byte marker key stands in for it.
        Without the marker an empty "directory" would not exist at all: a prefix is only
        visible while something lives under it.
        """
        pseudo_name, _ = self._get_pseudo_name_from_key(path)
        bucket = self._get_bucket(pseudo_name)
        marker_key = path.rstrip("/") + "/"

        # Anything under the prefix means the name is taken as a directory; an object at
        # the bare key means it is taken as a file.
        listing = bucket.meta.client.list_objects_v2(
            Bucket=bucket.name, Prefix=marker_key, MaxKeys=1
        )
        if listing.get("KeyCount", 0) > 0 or self.file_exists(path):
            raise FileExistsError(f"S3 key already in use: {marker_key}")

        bucket.Object(marker_key).put(Body=b"")

    # ------------------------------------------------------------------
    # File content read/write
    # ------------------------------------------------------------------

    async def read_file_chunk(self, path: str, offset: int, length: int) -> bytes:
        obj = self._get_object(path)
        range_header = f"bytes={offset}-{offset + length - 1}"

        def _read():
            response = obj.get(Range=range_header)
            return response["Body"].read()

        return await run_in_threadpool(_read)

    async def write_file(self, path: str, data: bytes) -> None:
        obj = self._get_object(path)

        def _write():
            obj.put(Body=data)

        await run_in_threadpool(_write)

    async def write_file_streaming(self, path: str, data_stream: AsyncIterator[bytes]) -> int:
        pseudo_name, _ = self._get_pseudo_name_from_key(path)
        bucket = self._get_bucket(pseudo_name)
        client = bucket.meta.client

        MIN_PART_SIZE = 5 * 1024 * 1024  # 5MB — S3 minimum part size

        mpu = await run_in_threadpool(
            client.create_multipart_upload,
            Bucket=bucket.name,
            Key=path,
        )
        upload_id = mpu["UploadId"]

        parts: list[dict] = []
        part_number = 1
        total_written = 0
        buffer = bytearray()

        try:
            async for chunk in data_stream:
                buffer.extend(chunk)
                total_written += len(chunk)

                while len(buffer) >= MIN_PART_SIZE:
                    part_data = bytes(buffer[:MIN_PART_SIZE])
                    buffer = bytearray(buffer[MIN_PART_SIZE:])

                    response = await run_in_threadpool(
                        client.upload_part,
                        Bucket=bucket.name,
                        Key=path,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=part_data,
                    )
                    parts.append({"PartNumber": part_number, "ETag": response["ETag"]})
                    part_number += 1

            if buffer or not parts:
                response = await run_in_threadpool(
                    client.upload_part,
                    Bucket=bucket.name,
                    Key=path,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=bytes(buffer),
                )
                parts.append({"PartNumber": part_number, "ETag": response["ETag"]})

            await run_in_threadpool(
                client.complete_multipart_upload,
                Bucket=bucket.name,
                Key=path,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )

            return total_written

        except Exception:
            await run_in_threadpool(
                client.abort_multipart_upload,
                Bucket=bucket.name,
                Key=path,
                UploadId=upload_id,
            )
            raise

    # ------------------------------------------------------------------
    # Path conversion
    # ------------------------------------------------------------------

    def convert_to_DB_format_path(self, path: str) -> str:
        """
        Convert path to DB logical format. Auto-detects input:
        - Logical path (starts with category): returns as-is
        - S3 key ("videos/Resource-1/..."): converts to logical

        A directory reaches this method in two shapes — a listing reports it as a
        CommonPrefix, which always ends in "/", while every other caller builds it as a
        plain key, which never does. The trailing slash is dropped so one directory has
        exactly one DB path: two spellings mean lookups keyed on this path (the
        user-created flag, a dir_metadata row, the parent walked out of ``dirname``) stop
        finding what the other spelling wrote.
        """
        path = path.rstrip("/")

        if path.startswith(self._category + "/"):
            return path
        pseudo_name, relative = self._get_pseudo_name_from_key(path)
        if relative:
            return f"{self._category}/{pseudo_name}/{relative}"
        return f"{self._category}/{pseudo_name}"

    def convert_to_FS_format_path(self, path: str) -> str:
        """
        Convert path to S3 key format. Auto-detects input:
        - Logical path (starts with category): converts to S3 key
        - S3 key (starts with VIDEO_PREFIX): returns as-is
        """
        if path.startswith(self.VIDEO_PREFIX + "/"):
            return path
        pseudo_name, relative = self._parse_logical_path(path)
        return self._build_video_key(pseudo_name, relative)

    def get_path_standard_format(self, path: str) -> str:
        """S3 keys always use forward slashes, normalize only."""
        return path.replace("\\", "/")

    # ------------------------------------------------------------------
    # External tool access
    # ------------------------------------------------------------------

    def get_ffmpeg_accessible_path(self, path: str) -> str | None:
        """Generate a pre-signed URL that ffmpeg can use as HTTP input."""
        try:
            pseudo_name, _ = self._get_pseudo_name_from_key(path)
            bucket = self._get_bucket(pseudo_name)
            client = bucket.meta.client
            return client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket.name, "Key": path},
                ExpiresIn=3600,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # File utilities (static)
    # ------------------------------------------------------------------

    @staticmethod
    def is_video_file(filename: str) -> bool:
        name = filename.rstrip("/").rsplit("/", 1)[-1]
        _, ext = posixpath.splitext(name.lower())
        return ext in get_settings().video_extensions
    
    @staticmethod
    def get_file_extension(filename: str) -> str:
        name = filename.rstrip("/").rsplit("/", 1)[-1]
        return posixpath.splitext(name)[1][1:]  # Exclude the dot

    @staticmethod
    def get_filename_without_extension(filename: str) -> str:
        name = filename.rstrip("/").rsplit("/", 1)[-1]
        return posixpath.splitext(name)[0]

    @staticmethod
    def join_path(*parts: str) -> str:
        return posixpath.join(*parts)

    @staticmethod
    def dirname(path: str) -> str:
        return posixpath.dirname(path)
