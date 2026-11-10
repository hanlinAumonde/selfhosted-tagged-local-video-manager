"""Asking the filesystem whether a rename between two directories would work."""

import errno
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _fs(path: Path) -> str:
    return str(path).replace("\\", "/")


def _tree(root: Path) -> list[str]:
    return sorted(str(path) for path in root.rglob("*"))


@pytest.fixture
def source(local_resource_dir: Path) -> Path:
    file = local_resource_dir / "source.mp4"
    file.write_bytes(b"source content")
    return file


@pytest.fixture
def other_dir(local_resource_dir: Path) -> Path:
    directory = local_resource_dir / "other"
    directory.mkdir()
    return directory


# Scenario: a rename inside one filesystem is reported as possible
#   Given a file "source.mp4" and a free target path in another directory of the mount
#   When can_rename is called
#   Then it returns True
#   And the source still holds its content
#   And nothing is left in either directory except the source
async def test_can_rename_reports_a_possible_rename_and_leaves_nothing_behind(
    local_handler, local_resource_dir, source, other_dir,
):
    before = _tree(local_resource_dir)

    possible = await local_handler.can_rename(_fs(source), _fs(other_dir / "target.mp4"))

    assert possible is True
    assert source.read_bytes() == b"source content"
    assert _tree(local_resource_dir) == before


# Scenario: the probe creates the target's parent directory
#   Given a file "source.mp4" and a target path inside a directory that does not exist
#   When can_rename is called
#   Then it returns True
#   And the target's parent directory exists
async def test_can_rename_creates_a_missing_target_directory(
    local_handler, local_resource_dir, source,
):
    target = local_resource_dir / "new" / "nested" / "target.mp4"

    possible = await local_handler.can_rename(_fs(source), _fs(target))

    assert possible is True
    assert target.parent.is_dir()


# Scenario: a refused rename is reported, not raised
#   Given a file "source.mp4"
#   And the filesystem rejects renames with a cross-device error
#   When can_rename is called
#   Then it returns False
#   And the probe file is gone from the source directory
async def test_can_rename_reports_false_and_removes_the_probe_when_refused(
    local_handler, local_resource_dir, source, other_dir, monkeypatch,
):
    def refuse(src, dst, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "rename", refuse)
    before = _tree(local_resource_dir)

    possible = await local_handler.can_rename(_fs(source), _fs(other_dir / "target.mp4"))

    assert possible is False
    assert _tree(local_resource_dir) == before


# Scenario: the probe crosses from the source's directory into the target's
#   Given a file "source.mp4" and a target path in another directory
#   And the filesystem refuses only renames between those two directories
#   When can_rename is called
#   Then it returns False
async def test_can_rename_tries_the_move_between_the_two_directories(
    local_handler, source, other_dir, monkeypatch,
):
    rename = os.rename

    def refuse_between_directories(src, dst, **kwargs):
        if os.path.dirname(src) != os.path.dirname(dst):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        rename(src, dst)

    monkeypatch.setattr(os, "rename", refuse_between_directories)

    possible = await local_handler.can_rename(_fs(source), _fs(other_dir / "target.mp4"))

    assert possible is False


# Scenario: a source directory that cannot hold a probe is reported, not raised
#   Given a source path in a directory that does not exist
#   When can_rename is called
#   Then it returns False
async def test_can_rename_reports_false_when_the_probe_cannot_be_created(
    local_handler, local_resource_dir, other_dir,
):
    source = local_resource_dir / "missing" / "source.mp4"

    possible = await local_handler.can_rename(_fs(source), _fs(other_dir / "target.mp4"))

    assert possible is False
