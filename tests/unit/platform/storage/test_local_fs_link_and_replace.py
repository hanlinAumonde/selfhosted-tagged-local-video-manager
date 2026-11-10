"""Moving a file on one filesystem without rewriting its bytes."""

import errno
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _fs(path: Path) -> str:
    return str(path).replace("\\", "/")


@pytest.fixture
def source(local_resource_dir: Path) -> Path:
    file = local_resource_dir / "source.mp4"
    file.write_bytes(b"source content")
    return file


# Scenario: linking gives the same file a second name
#   Given a file "source.mp4" on a local mount
#   When link_file is called with a free target path
#   Then it returns True
#   And the target has the same inode as the source
#   And the source still exists
async def test_link_file_gives_the_same_file_a_second_name(local_handler, local_resource_dir, source):
    target = local_resource_dir / "subdir" / "target.mp4"

    linked = await local_handler.link_file(_fs(source), _fs(target))

    assert linked is True
    assert target.stat().st_ino == source.stat().st_ino
    assert source.read_bytes() == b"source content"


# Scenario: linking creates the target's parent directory
#   Given a file "source.mp4" and a target path inside a directory that does not exist
#   When link_file is called
#   Then it returns True
#   And the target exists
async def test_link_file_creates_a_missing_target_directory(local_handler, local_resource_dir, source):
    target = local_resource_dir / "new" / "nested" / "target.mp4"

    linked = await local_handler.link_file(_fs(source), _fs(target))

    assert linked is True
    assert target.read_bytes() == b"source content"


# Scenario: a filesystem that refuses the link is reported, not raised
#   Given a file "source.mp4"
#   And the filesystem rejects hard links with a cross-device error
#   When link_file is called
#   Then it returns False
#   And no target file exists
async def test_link_file_reports_false_when_the_filesystem_refuses(
    local_handler, local_resource_dir, source, monkeypatch,
):
    def refuse(src, dst, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", refuse)
    target = local_resource_dir / "target.mp4"

    linked = await local_handler.link_file(_fs(source), _fs(target))

    assert linked is False
    assert not target.exists()


# Scenario: an occupied target is left alone
#   Given a file "source.mp4" and a different file already at the target path
#   When link_file is called
#   Then it returns False
#   And the target still holds its original content
async def test_link_file_leaves_an_occupied_target_untouched(local_handler, local_resource_dir, source):
    target = local_resource_dir / "target.mp4"
    target.write_bytes(b"already here")

    linked = await local_handler.link_file(_fs(source), _fs(target))

    assert linked is False
    assert target.read_bytes() == b"already here"


# Scenario: a link left by an earlier attempt counts as done
#   Given a target path that is already a hard link to "source.mp4"
#   When link_file is called
#   Then it returns True
#   And the source still holds its content
async def test_link_file_accepts_a_link_it_already_made(local_handler, local_resource_dir, source):
    target = local_resource_dir / "target.mp4"
    await local_handler.link_file(_fs(source), _fs(target))

    linked = await local_handler.link_file(_fs(source), _fs(target))

    assert linked is True
    assert source.read_bytes() == b"source content"


# Scenario: replacing puts a staged file onto an occupied target
#   Given a staged file with content "new" and a target file with content "old"
#   When replace_file is called
#   Then the target holds "new"
#   And the staged file no longer exists
async def test_replace_file_moves_the_staged_file_onto_an_occupied_target(local_handler, local_resource_dir):
    staged = local_resource_dir / "staged.part"
    staged.write_bytes(b"new")
    target = local_resource_dir / "target.mp4"
    target.write_bytes(b"old")

    await local_handler.replace_file(_fs(staged), _fs(target))

    assert target.read_bytes() == b"new"
    assert not staged.exists()
