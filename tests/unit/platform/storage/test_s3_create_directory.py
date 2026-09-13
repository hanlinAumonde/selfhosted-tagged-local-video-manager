"""
Behaviour specification — ``S3ResourceHandler.create_directory``.

Object storage has no directories: a prefix exists only while something lives under it,
so an empty folder needs a zero-byte marker key or it would not survive being created.

The refusal has to look at both shapes a name can already be taken in — anything under
the prefix means a directory, an object at the bare key means a file — because the
caller turns the refusal into "that name is taken" and must never adopt either.

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
NEW_DIR_KEY = f"videos/{PSEUDO_NAME}/new_folder"
MARKER_KEY = NEW_DIR_KEY + "/"


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


def _expect_prefix_is_empty(stub: Stubber) -> None:
    stub.add_response(
        "list_objects_v2",
        {"KeyCount": 0},
        {"Bucket": BUCKET, "Prefix": MARKER_KEY, "MaxKeys": 1},
    )


def _expect_no_object_at_the_bare_key(stub: Stubber) -> None:
    stub.add_client_error(
        "head_object",
        service_error_code="404",
        http_status_code=404,
        expected_params={"Bucket": BUCKET, "Key": NEW_DIR_KEY},
    )


# -----------------------------------------------------------------------
# ---------------------------- Happy path --------------------------------
# -----------------------------------------------------------------------

def test_create_directory_writes_a_marker_object(s3_handler: S3ResourceHandler, stub: Stubber):
    _expect_prefix_is_empty(stub)
    _expect_no_object_at_the_bare_key(stub)
    stub.add_response(
        "put_object", {}, {"Bucket": BUCKET, "Key": MARKER_KEY, "Body": b""}
    )

    s3_handler.create_directory(NEW_DIR_KEY)

    stub.assert_no_pending_responses()


# -----------------------------------------------------------------------
# ------------------------- Refusals -------------------------------------
# -----------------------------------------------------------------------

def test_create_directory_rejects_a_prefix_that_already_holds_something(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    stub.add_response(
        "list_objects_v2",
        {"KeyCount": 1, "Contents": [{"Key": MARKER_KEY + "movie.mp4", "Size": 10}]},
        {"Bucket": BUCKET, "Prefix": MARKER_KEY, "MaxKeys": 1},
    )

    with pytest.raises(FileExistsError):
        s3_handler.create_directory(NEW_DIR_KEY)

    stub.assert_no_pending_responses()


def test_create_directory_rejects_a_bare_key_held_by_a_file(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    _expect_prefix_is_empty(stub)
    stub.add_response(
        "head_object",
        {"ContentLength": 10},
        {"Bucket": BUCKET, "Key": NEW_DIR_KEY},
    )

    with pytest.raises(FileExistsError):
        s3_handler.create_directory(NEW_DIR_KEY)

    stub.assert_no_pending_responses()
