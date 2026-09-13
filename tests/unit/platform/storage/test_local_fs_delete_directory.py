"""
Behaviour specification — ``LocalFSResourceHandler.delete_directory``.

The counterpart to ``create_directory``, and deliberately the narrow one: it unlinks a
directory that holds nothing, and refuses anything else. The caller decides whether a
directory is empty enough to go — the handler never recurses, so a mistake upstream
costs one wrong refusal instead of a wrong tree.

``is_directory_empty`` is the question the caller asks first, and it is on the handler
rather than in the service because "what is left in here" is a storage question that S3
answers a different way.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# ------------------------- Deleting -------------------------------------
# -----------------------------------------------------------------------

def test_delete_directory_removes_an_empty_directory(
    local_handler, local_resource_dir: Path,
):
    target = local_resource_dir / "subdir" / "empty"
    assert target.is_dir()

    local_handler.delete_directory(str(target))

    assert not target.exists()


def test_delete_directory_refuses_a_directory_that_still_holds_a_file(
    local_handler, local_resource_dir: Path,
):
    target = local_resource_dir / "subdir"

    with pytest.raises(OSError):
        local_handler.delete_directory(str(target))

    assert target.is_dir()
    assert (target / "movie_c.mp4").is_file()


def test_delete_directory_refuses_a_directory_that_still_holds_a_sub_directory(
    local_handler, local_resource_dir: Path,
):
    target = local_resource_dir / "holder"
    target.mkdir()
    (target / "nested").mkdir()

    with pytest.raises(OSError):
        local_handler.delete_directory(str(target))

    assert (target / "nested").is_dir()


def test_delete_directory_raises_for_a_path_that_is_not_there(
    local_handler, local_resource_dir: Path,
):
    with pytest.raises(OSError):
        local_handler.delete_directory(str(local_resource_dir / "never_existed"))


# -----------------------------------------------------------------------
# --------------------- Asking what is left ------------------------------
# -----------------------------------------------------------------------

def test_is_directory_empty_is_true_for_a_directory_holding_nothing(
    local_handler, local_resource_dir: Path,
):
    assert local_handler.is_directory_empty(str(local_resource_dir / "subdir" / "empty"))


def test_is_directory_empty_is_false_when_a_non_video_file_remains(
    local_handler, local_resource_dir: Path,
):
    target = local_resource_dir / "docs"
    target.mkdir()
    (target / "readme.txt").write_text("not a video")

    assert local_handler.is_directory_empty(str(target)) is False


def test_is_directory_empty_is_false_when_a_sub_directory_remains(
    local_handler, local_resource_dir: Path,
):
    assert local_handler.is_directory_empty(str(local_resource_dir / "subdir")) is False
