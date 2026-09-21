"""Unit tests for LocalFSFileEntry — file metadata reading and construction modes."""

import os
from pathlib import Path
import pytest
from src.platform.storage.local_fs.local_fs_file_entry import LocalFSFileEntry

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# ------------------- Construction modes ---------------------------------
# -----------------------------------------------------------------------

def test_constructor_requires_dir_entry_or_file_path():
    with pytest.raises(ValueError):
        LocalFSFileEntry()


# -----------------------------------------------------------------------
# ------------------- file_path mode -------------------------------------
# -----------------------------------------------------------------------

def test_from_file_path_exposes_path_and_name(local_resource_dir: Path):
    file_path = local_resource_dir / "movie_a.mp4"
    entry = LocalFSFileEntry(file_path=str(file_path))

    assert Path(entry.path) == file_path
    assert entry.name == "movie_a.mp4"


def test_from_file_path_is_file_vs_is_dir(local_resource_dir: Path):
    file_entry = LocalFSFileEntry(file_path=str(local_resource_dir / "movie_a.mp4"))
    dir_entry = LocalFSFileEntry(file_path=str(local_resource_dir / "subdir"))

    assert file_entry.is_file() is True
    assert file_entry.is_dir() is False

    assert dir_entry.is_file() is False
    assert dir_entry.is_dir() is True


def test_from_file_path_stat_returns_size_and_mtime(local_resource_dir: Path):
    file_path = local_resource_dir / "movie_a.mp4"  # 100 bytes
    entry = LocalFSFileEntry(file_path=str(file_path))
    stat = entry.stat()
    assert stat.size == 100
    assert stat.mtime > 0


# -----------------------------------------------------------------------
# ------------------- dir_entry mode -------------------------------------
# -----------------------------------------------------------------------

def test_from_dir_entry_exposes_path_and_name(local_resource_dir: Path):
    with os.scandir(local_resource_dir) as it:
        dir_entries = sorted(it, key=lambda e: e.name)

    by_name = {e.name: LocalFSFileEntry(dir_entry=e) for e in dir_entries}

    assert "movie_a.mp4" in by_name
    movie_a = by_name["movie_a.mp4"]
    assert movie_a.name == "movie_a.mp4"
    assert Path(movie_a.path) == local_resource_dir / "movie_a.mp4"


def test_from_dir_entry_is_file_vs_is_dir(local_resource_dir: Path):
    with os.scandir(local_resource_dir) as it:
        by_name = {e.name: LocalFSFileEntry(dir_entry=e) for e in it}

    assert by_name["movie_a.mp4"].is_file() is True
    assert by_name["movie_a.mp4"].is_dir() is False
    assert by_name["subdir"].is_file() is False
    assert by_name["subdir"].is_dir() is True


def test_from_dir_entry_stat(local_resource_dir: Path):
    with os.scandir(local_resource_dir) as it:
        movie_a_entry = next(e for e in it if e.name == "movie_a.mp4")
        wrapper = LocalFSFileEntry(dir_entry=movie_a_entry)
        stat = wrapper.stat()
        assert stat.size == 100
        assert stat.mtime > 0
