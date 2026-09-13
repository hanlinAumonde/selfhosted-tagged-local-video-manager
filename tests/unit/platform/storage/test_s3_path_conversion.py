"""
Behaviour specification — one S3 directory, one DB path.

S3 hands a directory back in two shapes. A listing reports it as a CommonPrefix, which
always carries a trailing slash; everything else builds it as a plain key, which never
does. Both name the same directory, and the DB format has to spell it the same way from
either direction or the two spellings stop matching each other.

They did stop: ``create_directory`` recorded a folder under the no-slash spelling while
the listing looked it up under the slash spelling, so a newly created S3 folder was
never recognised as user-created and stayed hidden. The same split silently gave every
S3 sub-directory two ``dir_metadata`` rows, since ``dirname`` of the slash spelling is
the no-slash spelling of the same directory.
"""

import pytest

from src.config import S3HandlerConfig
from src.platform.storage.s3.s3_handler import S3ResourceHandler

pytestmark = pytest.mark.unit

CATEGORY = "S3-category"
PSEUDO_NAME = "Resource-1"


@pytest.fixture
def s3_handler() -> S3ResourceHandler:
    """Path conversion is pure string work; nothing here reaches the network."""
    return S3ResourceHandler(
        category=CATEGORY,
        pseudo_paths={PSEUDO_NAME: PSEUDO_NAME},
        handler_configs={
            PSEUDO_NAME: S3HandlerConfig(
                endpoint_url="http://localhost:9999",
                access_key="test-key",
                secret_key="test-secret",
                bucket="test-bucket",
            )
        },
    )


# -----------------------------------------------------------------------
# ------------- Both shapes of a directory agree ------------------------
# -----------------------------------------------------------------------

def test_a_listed_common_prefix_and_a_bare_key_give_the_same_db_path(
    s3_handler: S3ResourceHandler,
):
    from_listing = s3_handler.convert_to_DB_format_path(f"videos/{PSEUDO_NAME}/movies/")
    from_key = s3_handler.convert_to_DB_format_path(f"videos/{PSEUDO_NAME}/movies")

    assert from_listing == from_key == f"{CATEGORY}/{PSEUDO_NAME}/movies"


def test_a_pseudo_root_gives_the_same_db_path_in_both_shapes(
    s3_handler: S3ResourceHandler,
):
    with_slash = s3_handler.convert_to_DB_format_path(f"videos/{PSEUDO_NAME}/")
    without_slash = s3_handler.convert_to_DB_format_path(f"videos/{PSEUDO_NAME}")

    assert with_slash == without_slash == f"{CATEGORY}/{PSEUDO_NAME}"


def test_an_already_logical_path_is_normalised_too(s3_handler: S3ResourceHandler):
    converted = s3_handler.convert_to_DB_format_path(f"{CATEGORY}/{PSEUDO_NAME}/movies/")

    assert converted == f"{CATEGORY}/{PSEUDO_NAME}/movies"


# -----------------------------------------------------------------------
# ------------- What must not change ------------------------------------
# -----------------------------------------------------------------------

def test_a_video_file_key_converts_unchanged(s3_handler: S3ResourceHandler):
    converted = s3_handler.convert_to_DB_format_path(
        f"videos/{PSEUDO_NAME}/movies/movie_a.mp4"
    )

    assert converted == f"{CATEGORY}/{PSEUDO_NAME}/movies/movie_a.mp4"


def test_a_directory_db_path_still_round_trips_to_a_usable_key(
    s3_handler: S3ResourceHandler,
):
    db_path = f"{CATEGORY}/{PSEUDO_NAME}/movies"

    key = s3_handler.convert_to_FS_format_path(db_path)

    assert key == f"videos/{PSEUDO_NAME}/movies"
    assert s3_handler.convert_to_DB_format_path(key) == db_path
