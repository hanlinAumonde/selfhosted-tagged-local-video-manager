"""
Behaviour specification — the local filesystem handler's async IO surface.

The directory listing used to hand out lazy entries whose ``stat`` ran later, in the
caller, on the event loop — so even a listing moved onto a thread left the real IO
behind. Now a listing returns plain ``FileInfo`` values with size and mtime already
read, and nothing returned carries an IO method.

Fixture tree (``local_resource_dir``):
    movie_a.mp4 (100 B), movie_b.mp4 (200 B), notes.txt, subdir/movie_c.mp4 (300 B),
    subdir/empty/
"""

from pathlib import Path

import pytest

from src.platform.storage.file_info import FileInfo

pytestmark = pytest.mark.unit


async def _collect_walk(handler, root: Path) -> list[list[FileInfo]]:
    return [batch async for batch in handler.walk(str(root))]


# -----------------------------------------------------------------------
# ------------------------- list_directory -------------------------------
# -----------------------------------------------------------------------

# Scenario: a listing carries every entry with its metadata already read
#   Given the fixture directory
#   When list_directory is awaited on it
#   Then it returns one FileInfo per entry: movie_a.mp4, movie_b.mp4, notes.txt, subdir
#   And movie_a.mp4 reports size 100 and is_dir False
#   And subdir reports is_dir True
async def test_list_directory_returns_file_infos_with_size_and_type(
    local_handler, local_resource_dir: Path
):
    infos = await local_handler.list_directory(str(local_resource_dir))
    by_name = {info.name: info for info in infos}

    assert sorted(by_name) == ["movie_a.mp4", "movie_b.mp4", "notes.txt", "subdir"]
    assert by_name["movie_a.mp4"].size == 100
    assert by_name["movie_a.mp4"].is_dir is False
    assert by_name["movie_a.mp4"].mtime > 0
    assert by_name["subdir"].is_dir is True


# Scenario: a listing of a directory that is not there fails loudly
#   Given a path with nothing on disk
#   When list_directory is awaited on it
#   Then FileNotFoundError is raised — an empty list would read as "empty directory"
async def test_list_directory_of_a_missing_directory_raises(
    local_handler, local_resource_dir: Path
):
    with pytest.raises(FileNotFoundError):
        await local_handler.list_directory(str(local_resource_dir / "missing"))


# -----------------------------------------------------------------------
# ------------------------------ stat ------------------------------------
# -----------------------------------------------------------------------

# Scenario: stat answers existence, size and type in one call
#   Given movie_b.mp4 of 200 bytes
#   When stat is awaited on it
#   Then a FileInfo with name movie_b.mp4, size 200, is_dir False and a positive mtime
#       is returned
async def test_stat_of_a_file_returns_its_size_and_mtime(
    local_handler, local_resource_dir: Path
):
    info = await local_handler.stat(str(local_resource_dir / "movie_b.mp4"))

    assert info is not None
    assert info.name == "movie_b.mp4"
    assert info.size == 200
    assert info.is_dir is False
    assert info.mtime > 0


# Scenario: stat of a directory says it is a directory
#   Given subdir
#   When stat is awaited on it
#   Then a FileInfo with is_dir True is returned
async def test_stat_of_a_directory_reports_is_dir(local_handler, local_resource_dir: Path):
    info = await local_handler.stat(str(local_resource_dir / "subdir"))

    assert info is not None
    assert info.is_dir is True


# Scenario: stat of a missing path is None, not an exception
#   Given a path with nothing on disk
#   When stat is awaited on it
#   Then None is returned — "does it exist" is the question most callers are asking
async def test_stat_of_a_missing_path_returns_none(local_handler, local_resource_dir: Path):
    assert await local_handler.stat(str(local_resource_dir / "missing.mp4")) is None


# -----------------------------------------------------------------------
# ---------------------------- read_file ---------------------------------
# -----------------------------------------------------------------------

# Scenario: a whole small file is read in one call
#   Given movie_a.mp4 holding 100 bytes of b"a"
#   When read_file is awaited on it
#   Then exactly those 100 bytes come back
async def test_read_file_returns_the_whole_content(local_handler, local_resource_dir: Path):
    assert await local_handler.read_file(str(local_resource_dir / "movie_a.mp4")) == b"a" * 100


# Scenario: reading a file that is not there is None
#   Given a path with nothing on disk
#   When read_file is awaited on it
#   Then None is returned
async def test_read_file_of_a_missing_file_returns_none(
    local_handler, local_resource_dir: Path
):
    assert await local_handler.read_file(str(local_resource_dir / "missing.jpg")) is None


# -----------------------------------------------------------------------
# ------------------------------- walk -----------------------------------
# -----------------------------------------------------------------------

# Scenario: walk reaches every file in the tree
#   Given the fixture directory, with one file one level down
#   When every batch from walk is collected
#   Then the files seen are movie_a.mp4, movie_b.mp4, notes.txt and subdir/movie_c.mp4
#   And each carries its size (movie_c.mp4 reports 300)
async def test_walk_yields_every_file_below_the_root(local_handler, local_resource_dir: Path):
    batches = await _collect_walk(local_handler, local_resource_dir)
    files = {info.name: info for batch in batches for info in batch if not info.is_dir}

    assert sorted(files) == ["movie_a.mp4", "movie_b.mp4", "movie_c.mp4", "notes.txt"]
    assert files["movie_c.mp4"].size == 300
    assert files["movie_c.mp4"].path.endswith("subdir/movie_c.mp4")


# Scenario: walk reports the directories it passes through
#   Given the fixture directory, holding subdir and subdir/empty
#   When every batch from walk is collected
#   Then subdir and subdir/empty each appear as a FileInfo with is_dir True — a
#       directory with no file at all is otherwise invisible to a walk, and a caller
#       aggregating per directory would leave its stale record untouched
async def test_walk_yields_directories_including_empty_ones(
    local_handler, local_resource_dir: Path
):
    batches = await _collect_walk(local_handler, local_resource_dir)
    directories = sorted(
        Path(info.path).relative_to(local_resource_dir).as_posix()
        for batch in batches for info in batch if info.is_dir
    )

    assert directories == ["subdir", "subdir/empty"]


# Scenario: local walk batches by directory
#   Given the fixture directory
#   When the batches from walk are collected
#   Then the entries of the root arrive in one batch and those of subdir in another —
#       a caller can check for cancellation or report progress between directories
#   And an empty directory produces no batch of its own
async def test_walk_yields_one_batch_per_directory(local_handler, local_resource_dir: Path):
    batches = await _collect_walk(local_handler, local_resource_dir)
    names_per_batch = sorted(sorted(info.name for info in batch) for batch in batches)

    assert names_per_batch == [
        ["empty", "movie_c.mp4"],
        ["movie_a.mp4", "movie_b.mp4", "notes.txt", "subdir"],
    ]


# Scenario: walking a missing root fails loudly
#   Given a path with nothing on disk
#   When walk is iterated
#   Then FileNotFoundError is raised rather than an empty walk that reads as "no files"
async def test_walk_of_a_missing_root_raises(local_handler, local_resource_dir: Path):
    with pytest.raises(FileNotFoundError):
        await _collect_walk(local_handler, local_resource_dir / "missing")


# -----------------------------------------------------------------------
# ----------------------- read_file_streaming ----------------------------
# -----------------------------------------------------------------------

# Scenario: streaming a missing file fails before yielding anything
#   Given a path with nothing on disk
#   When read_file_streaming is iterated
#   Then FileNotFoundError is raised
async def test_read_file_streaming_of_a_missing_file_raises(
    local_handler, local_resource_dir: Path
):
    with pytest.raises(FileNotFoundError):
        async for _ in local_handler.read_file_streaming(str(local_resource_dir / "missing.mp4")):
            pass
