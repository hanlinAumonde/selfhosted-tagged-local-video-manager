"""
Behaviour specification — the S3 handler's async IO surface, on the low-level client.

Every method used to send a blocking boto3 request on the event loop, and the content
reads ran in threads on objects derived from ``boto3.resource`` — which boto3 documents
as not thread-safe. Now every request goes through the client, off the loop.

Driven through ``botocore.stub.Stubber``: no network, and the exact API calls — how many,
with which parameters — are part of what is asserted, because the number of round-trips
is the point of several of these methods.
"""

import io
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from src.config import S3HandlerConfig
from src.platform.storage.s3.s3_handler import S3ResourceHandler

pytestmark = pytest.mark.unit

BUCKET = "test-bucket"
CATEGORY = "S3-category"
PSEUDO_NAME = "S3-resource"
DIR_KEY = f"videos/{PSEUDO_NAME}/folder"
FILE_KEY = f"{DIR_KEY}/movie.mp4"
MODIFIED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


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
    stubber = Stubber(s3_handler._clients[PSEUDO_NAME])
    with stubber:
        yield stubber
    stubber.assert_no_pending_responses()


def _object(key: str, size: int = 10) -> dict:
    return {"Key": key, "Size": size, "LastModified": MODIFIED}


def _body(data: bytes) -> StreamingBody:
    return StreamingBody(io.BytesIO(data), len(data))


async def _collect_walk(handler: S3ResourceHandler, path: str) -> list[list]:
    return [batch async for batch in handler.walk(path)]


# -----------------------------------------------------------------------
# ------------------------- list_directory -------------------------------
# -----------------------------------------------------------------------

# Scenario: one directory level is listed with a delimiter
#   Given a prefix holding one object and one common prefix, plus its own marker object
#   When list_directory is awaited on the directory key
#   Then list_objects_v2 is called with Prefix "<key>/" and Delimiter "/"
#   And the object comes back as a FileInfo with its Size and LastModified
#   And the common prefix comes back as a FileInfo with is_dir True
#   And the directory's own marker is not listed as an entry of itself
async def test_list_directory_maps_objects_and_common_prefixes(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    stub.add_response(
        "list_objects_v2",
        {
            "CommonPrefixes": [{"Prefix": f"{DIR_KEY}/sub/"}],
            "Contents": [_object(f"{DIR_KEY}/", 0), _object(FILE_KEY, 2048)],
            "KeyCount": 3,
        },
        {"Bucket": BUCKET, "Prefix": f"{DIR_KEY}/", "Delimiter": "/"},
    )

    infos = await s3_handler.list_directory(DIR_KEY)
    by_name = {info.name: info for info in infos}

    assert sorted(by_name) == ["movie.mp4", "sub"]
    assert by_name["movie.mp4"].size == 2048
    assert by_name["movie.mp4"].mtime == MODIFIED.timestamp()
    assert by_name["movie.mp4"].is_dir is False
    assert by_name["sub"].is_dir is True


# -----------------------------------------------------------------------
# ------------------------------ stat ------------------------------------
# -----------------------------------------------------------------------

# Scenario: stat is one HEAD request
#   Given an object of 2048 bytes
#   When stat is awaited on its key
#   Then exactly one head_object call is made
#   And a FileInfo with size 2048 and the object's mtime is returned
async def test_stat_of_an_object_is_a_single_head_request(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    stub.add_response(
        "head_object",
        {"ContentLength": 2048, "LastModified": MODIFIED},
        {"Bucket": BUCKET, "Key": FILE_KEY},
    )

    info = await s3_handler.stat(FILE_KEY)

    assert info is not None
    assert info.name == "movie.mp4"
    assert info.size == 2048
    assert info.mtime == MODIFIED.timestamp()
    assert info.is_dir is False


# Scenario: stat of a missing key is None
#   Given head_object answers 404
#   When stat is awaited on the key
#   Then None is returned
async def test_stat_of_a_missing_key_returns_none(s3_handler: S3ResourceHandler, stub: Stubber):
    stub.add_client_error(
        "head_object", service_error_code="404", http_status_code=404,
        expected_params={"Bucket": BUCKET, "Key": FILE_KEY},
    )

    assert await s3_handler.stat(FILE_KEY) is None


# Scenario: a failure other than "not found" is not mistaken for absence
#   Given head_object answers 403
#   When stat is awaited on the key
#   Then the error is raised — reporting "missing" would make a permission problem look
#       like a deleted video
async def test_stat_raises_on_errors_other_than_not_found(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    stub.add_client_error(
        "head_object", service_error_code="403", http_status_code=403,
        expected_params={"Bucket": BUCKET, "Key": FILE_KEY},
    )

    with pytest.raises(ClientError):
        await s3_handler.stat(FILE_KEY)


# -----------------------------------------------------------------------
# ---------------------------- read_file ---------------------------------
# -----------------------------------------------------------------------

# Scenario: a stored thumbnail is read in one round-trip
#   Given an object holding b"thumbnail-bytes"
#   When read_file is awaited on its key
#   Then exactly one get_object call is made, with no HEAD before it
#   And the bytes come back
async def test_read_file_is_a_single_get_request(s3_handler: S3ResourceHandler, stub: Stubber):
    stub.add_response(
        "get_object",
        {"Body": _body(b"thumbnail-bytes")},
        {"Bucket": BUCKET, "Key": FILE_KEY},
    )

    assert await s3_handler.read_file(FILE_KEY) == b"thumbnail-bytes"


# Scenario: reading a missing key is None
#   Given get_object answers NoSuchKey
#   When read_file is awaited on the key
#   Then None is returned
async def test_read_file_of_a_missing_key_returns_none(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    stub.add_client_error(
        "get_object", service_error_code="NoSuchKey", http_status_code=404,
        expected_params={"Bucket": BUCKET, "Key": FILE_KEY},
    )

    assert await s3_handler.read_file(FILE_KEY) is None


# -----------------------------------------------------------------------
# ------------------------------- walk -----------------------------------
# -----------------------------------------------------------------------

# Scenario: walk lists the whole prefix flat, one page at a time
#   Given a prefix whose objects span two list_objects_v2 pages
#       (page one: a.mp4 and sub/b.mp4, truncated; page two: sub/deeper/c.mp4)
#   When the batches from walk are collected
#   Then list_objects_v2 is called without a Delimiter, the second time with the
#       continuation token from the first
#   And two batches arrive: [a.mp4, sub/b.mp4] then [sub/deeper/c.mp4]
async def test_walk_lists_the_prefix_flat_and_yields_per_page(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    stub.add_response(
        "list_objects_v2",
        {
            "Contents": [_object(f"{DIR_KEY}/a.mp4"), _object(f"{DIR_KEY}/sub/b.mp4")],
            "IsTruncated": True,
            "NextContinuationToken": "page-2",
            "KeyCount": 2,
        },
        {"Bucket": BUCKET, "Prefix": f"{DIR_KEY}/"},
    )
    stub.add_response(
        "list_objects_v2",
        {"Contents": [_object(f"{DIR_KEY}/sub/deeper/c.mp4")], "IsTruncated": False, "KeyCount": 1},
        {"Bucket": BUCKET, "Prefix": f"{DIR_KEY}/", "ContinuationToken": "page-2"},
    )

    batches = await _collect_walk(s3_handler, DIR_KEY)

    assert [[info.path for info in batch] for batch in batches] == [
        [f"{DIR_KEY}/a.mp4", f"{DIR_KEY}/sub/b.mp4"],
        [f"{DIR_KEY}/sub/deeper/c.mp4"],
    ]


# Scenario: a directory marker is reported as a directory, the root's own excepted
#   Given a prefix holding its own marker, a marker "sub/" for an otherwise empty
#       sub-directory, and a real object
#   When the batches from walk are collected
#   Then "sub/" appears as a FileInfo with is_dir True and name "sub" — a marker is the
#       only trace an empty S3 directory leaves, so it is how a walk learns of one
#   And the root's own marker does not appear, as it does not in list_directory
async def test_walk_reports_marker_objects_as_directories(
    s3_handler: S3ResourceHandler, stub: Stubber,
):
    stub.add_response(
        "list_objects_v2",
        {
            "Contents": [
                _object(f"{DIR_KEY}/", 0),
                _object(f"{DIR_KEY}/a.mp4"),
                _object(f"{DIR_KEY}/sub/", 0),
            ],
            "IsTruncated": False,
            "KeyCount": 3,
        },
        {"Bucket": BUCKET, "Prefix": f"{DIR_KEY}/"},
    )

    batches = await _collect_walk(s3_handler, DIR_KEY)
    infos = [info for batch in batches for info in batch]

    assert [(info.name, info.is_dir) for info in infos] == [("a.mp4", False), ("sub", True)]


# Scenario: walking a prefix with nothing under it fails loudly
#   Given list_objects_v2 answers with no keys at all
#   When walk is iterated
#   Then FileNotFoundError is raised — the same answer the local handler gives for a
#       missing root, so a caller can treat both backends alike
async def test_walk_of_an_empty_prefix_raises(s3_handler: S3ResourceHandler, stub: Stubber):
    stub.add_response(
        "list_objects_v2",
        {"IsTruncated": False, "KeyCount": 0},
        {"Bucket": BUCKET, "Prefix": f"{DIR_KEY}/"},
    )

    with pytest.raises(FileNotFoundError):
        await _collect_walk(s3_handler, DIR_KEY)


# -----------------------------------------------------------------------
# ------------------------- content transfer -----------------------------
# -----------------------------------------------------------------------

# Scenario: a ranged read asks the client for exactly that range
#   Given an object key
#   When read_file_chunk is awaited with offset 100 and length 50
#   Then get_object is called with Range "bytes=100-149"
#   And the body bytes come back
async def test_read_file_chunk_sends_the_byte_range(s3_handler: S3ResourceHandler, stub: Stubber):
    stub.add_response(
        "get_object",
        {"Body": _body(b"x" * 50)},
        {"Bucket": BUCKET, "Key": FILE_KEY, "Range": "bytes=100-149"},
    )

    assert await s3_handler.read_file_chunk(FILE_KEY, 100, 50) == b"x" * 50


# Scenario: a whole-file write is a single put
#   Given a key and b"data"
#   When write_file is awaited
#   Then put_object is called once with that key and body
async def test_write_file_puts_the_object(s3_handler: S3ResourceHandler, stub: Stubber):
    stub.add_response("put_object", {}, {"Bucket": BUCKET, "Key": FILE_KEY, "Body": b"data"})

    await s3_handler.write_file(FILE_KEY, b"data")


# Scenario: deleting a file is one delete request
#   Given an object key
#   When delete_file is awaited
#   Then delete_object is called once with that key
async def test_delete_file_deletes_the_object(s3_handler: S3ResourceHandler, stub: Stubber):
    stub.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": FILE_KEY})

    await s3_handler.delete_file(FILE_KEY)
