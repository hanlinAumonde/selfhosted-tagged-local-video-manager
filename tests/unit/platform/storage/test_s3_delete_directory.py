"""
Behaviour specification — ``S3ResourceHandler.delete_directory`` / ``is_directory_empty``.

Object storage has no directory to unlink. What ``create_directory`` left behind is a
zero-byte ``{key}/`` marker, so deleting the directory means deleting that marker — and
"is it empty" means "is the marker the only thing under this prefix".

That one-object difference is the whole reason emptiness is a handler question: on disk
it is a listing that comes back with nothing, here it is a listing that comes back with
exactly the marker.

Driven through ``botocore.stub.Stubber``: no network, and the exact API calls are part
of what is asserted.
"""

import pytest
from botocore.stub import Stubber

from src.config import S3HandlerConfig
from src.platform.storage.s3.s3_handler import S3ResourceHandler

pytestmark = pytest.mark.unit

BUCKET = "test-bucket"
CATEGORY = "S3-category"
PSEUDO_NAME = "S3-resource"
DIR_KEY = f"videos/{PSEUDO_NAME}/old_folder"
MARKER_KEY = DIR_KEY + "/"


@pytest.fixture
def s3_handler() -> S3ResourceHandler:
    """A handler pointed at an endpoint nothing listens on; every call is stubbed."""
    return S3ResourceHandler(
        category=CATEGORY,
        pseudo_paths={PSEUDO_NAME: PSEUDO_NAME},
        handler_configs={
            PSEUDO_NAME: S3HandlerConfig(
                endpoint_url="http://localhost:9999",
                access_key="test-key",
                secret_key="test-secret",
                bucket=BUCKET,
            )
        },
    )


@pytest.fixture
def stub(s3_handler: S3ResourceHandler) -> Stubber:
    stubber = Stubber(s3_handler._buckets[PSEUDO_NAME].meta.client)
    with stubber:
        yield stubber


def _expect_listing(stub: Stubber, *keys: str) -> None:
    """The prefix listing the handler uses to decide whether anything is left."""
    stub.add_response(
        "list_objects_v2",
        {
            "KeyCount": len(keys),
            "Contents": [{"Key": key, "Size": 0} for key in keys],
        },
        {"Bucket": BUCKET, "Prefix": MARKER_KEY, "MaxKeys": 2},
    )


# -----------------------------------------------------------------------
# ------------------------- Deleting -------------------------------------
# -----------------------------------------------------------------------

def test_delete_directory_deletes_the_marker_object(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    _expect_listing(stub, MARKER_KEY)
    stub.add_response(
        "delete_object", {}, {"Bucket": BUCKET, "Key": MARKER_KEY}
    )

    s3_handler.delete_directory(DIR_KEY)

    stub.assert_no_pending_responses()


def test_delete_directory_refuses_a_prefix_that_still_holds_an_object(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    _expect_listing(stub, MARKER_KEY, MARKER_KEY + "movie.mp4")

    with pytest.raises(OSError):
        s3_handler.delete_directory(DIR_KEY)

    stub.assert_no_pending_responses()


def test_delete_directory_is_not_confused_by_a_path_without_a_trailing_slash(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    _expect_listing(stub, MARKER_KEY)
    stub.add_response(
        "delete_object", {}, {"Bucket": BUCKET, "Key": MARKER_KEY}
    )

    # The same directory, written the way a listing reports it.
    s3_handler.delete_directory(MARKER_KEY)

    stub.assert_no_pending_responses()


# -----------------------------------------------------------------------
# --------------------- Asking what is left ------------------------------
# -----------------------------------------------------------------------

def test_is_directory_empty_is_true_when_only_the_marker_is_under_the_prefix(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    _expect_listing(stub, MARKER_KEY)

    assert s3_handler.is_directory_empty(DIR_KEY) is True


def test_is_directory_empty_is_false_when_another_object_is_under_the_prefix(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    _expect_listing(stub, MARKER_KEY, MARKER_KEY + "movie.mp4")

    assert s3_handler.is_directory_empty(DIR_KEY) is False


def test_is_directory_empty_is_true_for_a_prefix_with_no_keys_at_all(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    stub.add_response(
        "list_objects_v2",
        {"KeyCount": 0},
        {"Bucket": BUCKET, "Prefix": MARKER_KEY, "MaxKeys": 2},
    )

    assert s3_handler.is_directory_empty(DIR_KEY) is True
