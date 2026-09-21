"""Unit tests for LocalFSResourceHandler — directory listing and IO operations."""

from pathlib import Path

import pytest

from src.config import Settings
from src.platform.storage.local_fs.local_fs_handler import LocalFSResourceHandler

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# --------------------- IO operations ------------------------------------
# -----------------------------------------------------------------------

def test_list_directory_yields_each_entry(local_handler, local_resource_dir: Path):
    with local_handler.list_directory(str(local_resource_dir)) as entries:
        names = sorted(e.name for e in entries)
    assert names == ["movie_a.mp4", "movie_b.mp4", "notes.txt", "subdir"]


def test_list_directory_subdir(local_handler, local_resource_dir: Path):
    with local_handler.list_directory(str(local_resource_dir / "subdir")) as entries:
        names = sorted(e.name for e in entries)
    assert names == ["empty", "movie_c.mp4"]


def test_get_entry_returns_file_entry(local_handler, local_resource_dir: Path):
    entry = local_handler.get_entry(str(local_resource_dir / "movie_a.mp4"))
    assert entry.name == "movie_a.mp4"
    assert entry.is_file() is True
    assert entry.is_dir() is False


def test_get_size_returns_byte_count(local_handler, local_resource_dir: Path):
    assert local_handler.get_size(str(local_resource_dir / "movie_a.mp4")) == 100
    assert local_handler.get_size(str(local_resource_dir / "movie_b.mp4")) == 200


def test_file_exists_true_and_false(local_handler, local_resource_dir: Path):
    assert local_handler.file_exists(str(local_resource_dir / "movie_a.mp4")) is True
    assert local_handler.file_exists(str(local_resource_dir / "missing.mp4")) is False


def test_delete_file_removes_from_disk(local_handler, local_resource_dir: Path):
    target = local_resource_dir / "movie_a.mp4"
    assert target.exists()
    local_handler.delete_file(str(target))
    assert not target.exists()


# -----------------------------------------------------------------------
# --------------------- Async file content ops ---------------------------
# -----------------------------------------------------------------------

async def test_read_file_chunk_returns_requested_range(
    local_handler, local_resource_dir: Path
):
    """movie_b.mp4 is 200 bytes of 'b'. Read 50 bytes from offset 100."""
    chunk = await local_handler.read_file_chunk(
        str(local_resource_dir / "movie_b.mp4"), offset=100, length=50,
    )
    assert chunk == b"b" * 50


async def test_read_file_chunk_truncates_at_eof(
    local_handler, local_resource_dir: Path
):
    """Reading past EOF returns whatever is available, not padded."""
    chunk = await local_handler.read_file_chunk(
        str(local_resource_dir / "movie_a.mp4"), offset=90, length=100,
    )
    assert chunk == b"a" * 10


async def test_write_file_creates_parent_directories(
    local_handler, tmp_path: Path
):
    target = tmp_path / "deep" / "nested" / "out.bin"
    await local_handler.write_file(str(target), b"hello")
    assert target.read_bytes() == b"hello"


async def test_write_file_overwrites(local_handler, tmp_path: Path):
    target = tmp_path / "out.bin"
    await local_handler.write_file(str(target), b"first")
    await local_handler.write_file(str(target), b"second")
    assert target.read_bytes() == b"second"


# -----------------------------------------------------------------------
# --------------------- resolve_path -------------------------------------
# -----------------------------------------------------------------------

def test_resolve_path_returns_category_when_pseudo_is_none(local_handler):
    assert local_handler.resolve_path("Test-category", None, None) == "Test-category"


def test_resolve_path_with_pseudo_returns_host_path_no_root(local_handler, local_resource_dir):
    """Without ROOT_PATH, resolve_path falls back to the configured host path."""
    expected = str(local_resource_dir).replace("\\", "/")
    assert (
        local_handler.resolve_path("Test-category", "Test-resource", None)
        == expected
    )


def test_resolve_path_appends_sub_path(local_handler, local_resource_dir):
    expected = (str(local_resource_dir) + "/subdir").replace("\\", "/")
    actual = local_handler.resolve_path(
        "Test-category", "Test-resource", "/subdir",
    )
    # Normalize for comparison since join might prefix differently on Windows.
    assert actual == expected


def test_resolve_path_with_root_path_uses_mount_layout(tmp_path: Path):
    """When ROOT_PATH is set, resolve uses ROOT_PATH/{category}/{pseudo} layout."""
    handler = LocalFSResourceHandler(
        category="Cat",
        pseudo_paths={"P1": "/ignored/host"},
        root_path=str(tmp_path),
    )
    expected = (str(tmp_path) + "/Cat/P1").replace("\\", "/")
    assert handler.resolve_path("Cat", "P1", None) == expected


# -----------------------------------------------------------------------
# --------------------- Path conversion ----------------------------------
# -----------------------------------------------------------------------

def test_convert_to_db_format_logical_passes_through(local_handler):
    assert (
        local_handler.convert_to_DB_format_path("Test-category/Test-resource/movie_a.mp4")
        == "Test-category/Test-resource/movie_a.mp4"
    )


def test_convert_to_db_format_fs_path_to_logical(local_handler, local_resource_dir):
    fs = str(local_resource_dir / "movie_a.mp4")
    assert (
        local_handler.convert_to_DB_format_path(fs)
        == "Test-category/Test-resource/movie_a.mp4"
    )


def test_convert_to_db_format_root_path_layout(tmp_path: Path):
    handler = LocalFSResourceHandler(
        category="Cat",
        pseudo_paths={"P1": "/ignored"},
        root_path=str(tmp_path),
    )
    fs = (str(tmp_path) + "/Cat/P1/folder/movie.mp4").replace("\\", "/")
    assert handler.convert_to_DB_format_path(fs) == "Cat/P1/folder/movie.mp4"


def test_convert_to_db_format_unknown_path_passes_through(local_handler):
    """Path that doesn't match any pseudo nor the logical prefix is returned standardized."""
    assert (
        local_handler.convert_to_DB_format_path("/totally/unrelated/path")
        == "/totally/unrelated/path"
    )


def test_convert_to_fs_format_logical_to_fs(local_handler, local_resource_dir):
    expected = (str(local_resource_dir) + "/movie_a.mp4").replace("\\", "/")
    assert (
        local_handler.convert_to_FS_format_path("Test-category/Test-resource/movie_a.mp4")
        == expected
    )


def test_convert_to_fs_format_already_fs(local_handler, local_resource_dir):
    fs = str(local_resource_dir / "movie_a.mp4").replace("\\", "/")
    assert local_handler.convert_to_FS_format_path(fs) == fs


def test_get_path_standard_format_normalizes_backslashes(local_handler):
    assert local_handler.get_path_standard_format("a\\b\\c") == "a/b/c"


# -----------------------------------------------------------------------
# --------------------- External tool access -----------------------------
# -----------------------------------------------------------------------

def test_get_ffmpeg_accessible_path_returns_input(local_handler):
    assert local_handler.get_ffmpeg_accessible_path("/some/path.mp4") == "/some/path.mp4"


# -----------------------------------------------------------------------
# --------------------- File utilities (static) --------------------------
# -----------------------------------------------------------------------

def test_is_video_file_uses_settings_extensions(fs_settings: Settings):
    assert LocalFSResourceHandler.is_video_file("video.mp4") is True
    assert LocalFSResourceHandler.is_video_file("video.MP4") is True
    assert LocalFSResourceHandler.is_video_file("notes.txt") is False
    assert LocalFSResourceHandler.is_video_file("no-extension") is False


def test_get_file_extension():
    assert LocalFSResourceHandler.get_file_extension("video.mp4") == "mp4"
    assert LocalFSResourceHandler.get_file_extension("archive.tar.gz") == "gz"
    assert LocalFSResourceHandler.get_file_extension("no_extension") == ""


def test_get_filename_without_extension():
    assert LocalFSResourceHandler.get_filename_without_extension("video.mp4") == "video"
    assert LocalFSResourceHandler.get_filename_without_extension("/a/b/video.mp4") == "video"
    assert LocalFSResourceHandler.get_filename_without_extension("archive.tar.gz") == "archive.tar"


def test_join_path_uses_forward_slashes():
    assert LocalFSResourceHandler.join_path("a", "b", "c") == "a/b/c"


def test_dirname_uses_forward_slashes():
    assert LocalFSResourceHandler.dirname("a/b/c.mp4") == "a/b"
    assert LocalFSResourceHandler.dirname("only_file.mp4") == ""


# -----------------------------------------------------------------------
# --------------------- write_file_streaming ----------------------------
# -----------------------------------------------------------------------

async def test_write_file_streaming_creates_file(local_handler, tmp_path: Path):
    target = tmp_path / "streamed" / "out.bin"

    async def _chunks():
        yield b"chunk1"
        yield b"chunk2"
        yield b"chunk3"

    total = await local_handler.write_file_streaming(str(target), _chunks())
    assert total == 18
    assert target.read_bytes() == b"chunk1chunk2chunk3"


# -----------------------------------------------------------------------
# --------------------- get_available_space -----------------------------
# -----------------------------------------------------------------------

def test_get_available_space_returns_positive_int(local_handler, local_resource_dir: Path):
    space = local_handler.get_available_space(str(local_resource_dir / "movie_a.mp4"))
    assert isinstance(space, int)
    assert space > 0


def test_get_available_space_invalid_path_returns_none(local_handler):
    space = local_handler.get_available_space("Z:/nonexistent/path/file.mp4")
    assert space is None


# -----------------------------------------------------------------------
# --------------------- read_file_streaming (from base class) -----------
# -----------------------------------------------------------------------

async def test_read_file_streaming_yields_all_data(
    local_handler, local_resource_dir: Path
):
    path = str(local_resource_dir / "movie_b.mp4")
    chunks = []
    async for chunk in local_handler.read_file_streaming(path, chunk_size=80):
        chunks.append(chunk)
    full = b"".join(chunks)
    assert full == b"b" * 200
    assert len(chunks) == 3  # 80 + 80 + 40


# -----------------------------------------------------------------------
# --- convert_to_db/fs with root_path deep paths (line 112, 140) --------
# -----------------------------------------------------------------------

def test_convert_to_db_root_path_pseudo_root_no_relative(tmp_path: Path):
    handler = LocalFSResourceHandler(
        category="Cat", pseudo_paths={"P1": "/ignored"}, root_path=str(tmp_path),
    )
    mounted_root = (str(tmp_path) + "/Cat/P1").replace("\\", "/")
    assert handler.convert_to_DB_format_path(mounted_root) == "Cat/P1"


def test_convert_to_fs_root_path_with_relative(tmp_path: Path):
    handler = LocalFSResourceHandler(
        category="Cat", pseudo_paths={"P1": "/ignored"}, root_path=str(tmp_path),
    )
    expected = (str(tmp_path) + "/Cat/P1/sub/file.mp4").replace("\\", "/")
    assert handler.convert_to_FS_format_path("Cat/P1/sub/file.mp4") == expected
