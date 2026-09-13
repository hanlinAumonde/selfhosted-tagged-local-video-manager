"""
Behaviour specification — ``LocalFSResourceHandler.create_directory``.

Creating a directory is the one write the browser needs that is not a file write, so it
joins the handler interface rather than being done with ``os`` calls from a feature.
Refusing an existing path is part of the contract: the caller turns that refusal into a
"name already taken" message, and must not be able to silently adopt someone else's
directory instead.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# ---------------------------- Happy path --------------------------------
# -----------------------------------------------------------------------

def test_create_directory_creates_the_directory_on_disk(
    local_handler, local_resource_dir: Path,
):
    target = local_resource_dir / "new_folder"
    assert not target.exists()

    local_handler.create_directory(str(target))

    assert target.is_dir()


# -----------------------------------------------------------------------
# ------------------------- Refusals -------------------------------------
# -----------------------------------------------------------------------

def test_create_directory_rejects_an_existing_directory(
    local_handler, local_resource_dir: Path,
):
    existing = local_resource_dir / "subdir"

    with pytest.raises(FileExistsError):
        local_handler.create_directory(str(existing))


def test_create_directory_rejects_an_existing_file(
    local_handler, local_resource_dir: Path,
):
    existing = local_resource_dir / "movie_a.mp4"

    with pytest.raises(FileExistsError):
        local_handler.create_directory(str(existing))

    assert existing.is_file()
    assert existing.read_bytes() == b"a" * 100
