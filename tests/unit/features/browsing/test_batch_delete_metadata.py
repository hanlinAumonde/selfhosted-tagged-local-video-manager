"""A batch delete has to refresh the stored size of every directory that lost a video,
not only the directory the request was made from: a selection can reach into
sub-directories (directory search results, or a "Delete all" walking the tree).
"""

from pathlib import Path

import pytest

from src.features.browsing.batch_operation_service import DirectoryDeletionStrategy
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.platform.storage.absolute_path import AbsolutePath
from src.platform.storage.resource_handler_service import ResourceHandlerService

pytestmark = pytest.mark.unit

CATEGORY = "Test-category"
ROOT_DB = "Test-category/Test-resource"
SUBDIR_DB = f"{ROOT_DB}/subdir"


def _root(handler_svc: ResourceHandlerService, root: Path) -> AbsolutePath:
    return AbsolutePath.from_existing_path(
        path=str(root).replace("\\", "/"),
        category=CATEGORY,
        handler=handler_svc.get_handler(CATEGORY),
    )


async def _stored_size(dir_meta_svc: DirMetadataService, db_path: str) -> float:
    total_size, _ = await dir_meta_svc.get_metadata(CATEGORY, db_path)
    return total_size


@pytest.fixture
async def seeded(video_factory, dir_meta_svc, local_resource_handler_service, local_resource_dir):
    """The three videos as browsing would have stored them, with the tree's sizes recorded."""
    videos = {
        name: await video_factory(name=name, path=path)
        for name, path in [
            ("movie_a", f"{ROOT_DB}/movie_a.mp4"),
            ("movie_b", f"{ROOT_DB}/movie_b.mp4"),
            ("movie_c", f"{SUBDIR_DB}/movie_c.mp4"),
        ]
    }
    await dir_meta_svc.calculate_directory_metadata(
        _root(local_resource_handler_service, local_resource_dir),
        skipCache=True, recursiveCalculation=True,
    )
    # Hand-checked against the fixture tree, so a wrong starting point fails here.
    assert await _stored_size(dir_meta_svc, ROOT_DB) == 600
    assert await _stored_size(dir_meta_svc, SUBDIR_DB) == 300
    return videos


class TestBatchDeleteRefreshesEveryDirectoryItTouched:
    async def test_deleting_videos_by_id_refreshes_the_sub_directory_they_were_in(
        self, batch_svc, dir_meta_svc, seeded,
        local_resource_handler_service, local_resource_dir,
    ):
        """
        Given movie_a.mp4 (100 B) and movie_b.mp4 (200 B) in the resource root
        And subdir/movie_c.mp4 (300 B)
        And the stored metadata says the root holds 600 bytes and subdir 300 bytes
        When a batch delete made from the root removes movie_a and movie_c by id
        Then the stored metadata says subdir holds 0 bytes
        And the stored metadata says the root holds 200 bytes
        """
        events = [e async for e in batch_svc.batch_delete(
            dir_path=_root(local_resource_handler_service, local_resource_dir),
            videoIds=[str(seeded["movie_a"].id), str(seeded["movie_c"].id)],
            fileEntries=None,
        )]

        assert events[-1].message == "Deleted 2 out of 2 videos"
        assert await _stored_size(dir_meta_svc, SUBDIR_DB) == 0
        assert await _stored_size(dir_meta_svc, ROOT_DB) == 200

    async def test_delete_all_keeping_the_folder_refreshes_its_sub_directories(
        self, batch_svc, browse_svc, dir_meta_svc, seeded,
        local_resource_handler_service, local_resource_dir,
    ):
        """
        Given movie_a.mp4 (100 B), movie_b.mp4 (200 B) and subdir/movie_c.mp4 (300 B)
        And the stored metadata says the root holds 600 bytes and subdir 300 bytes
        When "Delete all" on the root removes all three, choosing KeepFolder
        Then the stored metadata says subdir holds 0 bytes
        And the stored metadata says the root holds 0 bytes
        """
        # The walk the subscription resolver hands to a "Delete all".
        entries = await browse_svc.get_all_video_entries_in_directory(
            str(local_resource_dir).replace("\\", "/"), CATEGORY
        )

        events = [e async for e in batch_svc.batch_delete(
            dir_path=_root(local_resource_handler_service, local_resource_dir),
            videoIds=None,
            fileEntries=entries,
            directoryDeletion=DirectoryDeletionStrategy.KeepFolder,
        )]

        assert events[-1].message == "Deleted 3 out of 3 videos"
        assert await _stored_size(dir_meta_svc, SUBDIR_DB) == 0
        assert await _stored_size(dir_meta_svc, ROOT_DB) == 0
