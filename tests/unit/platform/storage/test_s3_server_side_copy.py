"""
Behaviour specification — copying an object inside one bucket without downloading it.

S3 has no rename: moving an object inside a bucket is a copy followed by a delete. The
copy is done by the server, part by part (UploadPartCopy), so no bytes pass through this
process and no single request has to outlive the client's read timeout.

Driven through ``botocore.stub.Stubber``: the byte ranges asked for and the parts the
upload is completed with are the contract.
"""

from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from src.config import S3HandlerConfig
from src.platform.storage.local_fs.local_fs_handler import LocalFSResourceHandler
from src.platform.storage.s3.s3_handler import S3ResourceHandler

pytestmark = pytest.mark.unit

CATEGORY = "S3-category"
MODIFIED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
SOURCE_KEY = "videos/R1/movie.mp4"
TARGET_KEY = "videos/R1/shelf/movie.mp4"
UPLOAD_ID = "upload-1"


def _mount(endpoint: str, bucket: str) -> S3HandlerConfig:
    return S3HandlerConfig(
        endpoint_url=endpoint, access_key="test-key", secret_key="test-secret", bucket=bucket,
    )


@pytest.fixture
def s3_handler(monkeypatch) -> S3ResourceHandler:
    """Four mounts on endpoints nothing listens on; every call is stubbed.

    R1 and R2 share an endpoint and a bucket, R3 is another bucket, R4 another endpoint.
    """
    monkeypatch.setattr(S3ResourceHandler, "COPY_PART_SIZE", 10)
    return S3ResourceHandler(
        category=CATEGORY,
        pseudo_paths={name: name for name in ("R1", "R2", "R3", "R4")},
        handler_configs={
            "R1": _mount("http://localhost:9999", "videos"),
            "R2": _mount("http://localhost:9999", "videos"),
            "R3": _mount("http://localhost:9999", "archive"),
            "R4": _mount("http://localhost:8888", "videos"),
        },
    )


@pytest.fixture
def stubs(s3_handler: S3ResourceHandler) -> dict[str, Stubber]:
    """One active stubber per mount, so a request nobody queued an answer for fails."""
    stubbers = {name: Stubber(client) for name, client in s3_handler._clients.items()}
    for stubber in stubbers.values():
        stubber.activate()
    yield stubbers
    for stubber in stubbers.values():
        stubber.deactivate()
        stubber.assert_no_pending_responses()


def _ignore_progress(copied: int) -> None:
    pass


def _expect_head(stub: Stubber, key: str, size: int) -> None:
    stub.add_response(
        "head_object",
        {"ContentLength": size, "LastModified": MODIFIED},
        {"Bucket": "videos", "Key": key},
    )


def _expect_upload_created(stub: Stubber, key: str) -> None:
    stub.add_response(
        "create_multipart_upload", {"UploadId": UPLOAD_ID}, {"Bucket": "videos", "Key": key},
    )


def _part_params(source: str, target: str, number: int, byte_range: str) -> dict:
    return {
        "Bucket": "videos",
        "Key": target,
        "UploadId": UPLOAD_ID,
        "PartNumber": number,
        "CopySource": {"Bucket": "videos", "Key": source},
        "CopySourceRange": byte_range,
    }


def _expect_part(stub: Stubber, source: str, target: str, number: int, byte_range: str) -> None:
    stub.add_response(
        "upload_part_copy",
        {"CopyPartResult": {"ETag": f'"etag-{number}"'}},
        _part_params(source, target, number, byte_range),
    )


def _expect_completed(stub: Stubber, key: str, part_numbers: list[int]) -> None:
    stub.add_response(
        "complete_multipart_upload",
        {},
        {
            "Bucket": "videos",
            "Key": key,
            "UploadId": UPLOAD_ID,
            "MultipartUpload": {
                "Parts": [{"PartNumber": n, "ETag": f'"etag-{n}"'} for n in part_numbers]
            },
        },
    )


def _expect_aborted(stub: Stubber, key: str) -> None:
    stub.add_response(
        "abort_multipart_upload", {}, {"Bucket": "videos", "Key": key, "UploadId": UPLOAD_ID},
    )


# -----------------------------------------------------------------------
# ------------------------- copying in parts ----------------------------
# -----------------------------------------------------------------------

# Scenario: an object is copied by the server in ranged parts
#   Given a part size of 10 bytes
#   And an object of 25 bytes in the bucket
#   When copy_server_side is awaited from its key to another key of the same mount
#   Then a multipart upload is created at the target key
#   And upload_part_copy is called three times, with CopySource naming the bucket and
#       source key, and CopySourceRange "bytes=0-9", "bytes=10-19", "bytes=20-24"
#   And the upload is completed with parts 1, 2, 3 and the ETags those calls returned
#   And True is returned
async def test_an_object_is_copied_by_the_server_in_ranged_parts(s3_handler, stubs):
    stub = stubs["R1"]
    _expect_head(stub, SOURCE_KEY, 25)
    _expect_upload_created(stub, TARGET_KEY)
    _expect_part(stub, SOURCE_KEY, TARGET_KEY, 1, "bytes=0-9")
    _expect_part(stub, SOURCE_KEY, TARGET_KEY, 2, "bytes=10-19")
    _expect_part(stub, SOURCE_KEY, TARGET_KEY, 3, "bytes=20-24")
    _expect_completed(stub, TARGET_KEY, [1, 2, 3])

    assert await s3_handler.copy_server_side(SOURCE_KEY, TARGET_KEY, _ignore_progress) is True


# Scenario: progress is reported after every part
#   Given a part size of 10 bytes
#   And an object of 25 bytes in the bucket
#   When copy_server_side is awaited with a progress callback
#   Then the callback receives 10, 20, 25 — the bytes copied so far, in that order
async def test_progress_is_reported_after_every_part(s3_handler, stubs):
    stub = stubs["R1"]
    _expect_head(stub, SOURCE_KEY, 25)
    _expect_upload_created(stub, TARGET_KEY)
    _expect_part(stub, SOURCE_KEY, TARGET_KEY, 1, "bytes=0-9")
    _expect_part(stub, SOURCE_KEY, TARGET_KEY, 2, "bytes=10-19")
    _expect_part(stub, SOURCE_KEY, TARGET_KEY, 3, "bytes=20-24")
    _expect_completed(stub, TARGET_KEY, [1, 2, 3])
    reported: list[int] = []

    await s3_handler.copy_server_side(SOURCE_KEY, TARGET_KEY, reported.append)

    assert reported == [10, 20, 25]


# Scenario: an object smaller than one part is a single part covering all of it
#   Given a part size of 10 bytes
#   And an object of 4 bytes in the bucket
#   When copy_server_side is awaited
#   Then upload_part_copy is called once with CopySourceRange "bytes=0-3"
#   And the upload is completed with that one part
async def test_an_object_smaller_than_one_part_is_copied_as_a_single_part(s3_handler, stubs):
    stub = stubs["R1"]
    _expect_head(stub, SOURCE_KEY, 4)
    _expect_upload_created(stub, TARGET_KEY)
    _expect_part(stub, SOURCE_KEY, TARGET_KEY, 1, "bytes=0-3")
    _expect_completed(stub, TARGET_KEY, [1])

    assert await s3_handler.copy_server_side(SOURCE_KEY, TARGET_KEY, _ignore_progress) is True


# Scenario: two mounts on the same endpoint and bucket copy server-side
#   Given mounts "R1" and "R2" configured with the same endpoint and bucket
#   And an object under "videos/R1/"
#   When copy_server_side is awaited to a key under "videos/R2/"
#   Then the copy is made by the server
#   And True is returned
async def test_two_mounts_sharing_a_bucket_copy_server_side(s3_handler, stubs):
    target_key = "videos/R2/movie.mp4"
    _expect_head(stubs["R1"], SOURCE_KEY, 4)
    _expect_upload_created(stubs["R2"], target_key)
    _expect_part(stubs["R2"], SOURCE_KEY, target_key, 1, "bytes=0-3")
    _expect_completed(stubs["R2"], target_key, [1])

    assert await s3_handler.copy_server_side(SOURCE_KEY, target_key, _ignore_progress) is True


# -----------------------------------------------------------------------
# ---------------------- declining, so the caller streams ---------------
# -----------------------------------------------------------------------

# Scenario: mounts on different buckets are declined
#   Given mounts "R1" on bucket "videos" and "R3" on bucket "archive"
#   When copy_server_side is awaited from a key under "videos/R1/" to one under "videos/R3/"
#   Then False is returned
#   And no request is sent at all
async def test_a_copy_between_buckets_is_declined_without_a_request(s3_handler, stubs):
    copied = await s3_handler.copy_server_side(
        SOURCE_KEY, "videos/R3/movie.mp4", _ignore_progress
    )

    assert copied is False


# Scenario: mounts on different endpoints are declined
#   Given mounts "R1" and "R4" with the same bucket name on two different endpoints
#   When copy_server_side is awaited from a key under "videos/R1/" to one under "videos/R4/"
#   Then False is returned
#   And no request is sent at all
async def test_a_copy_between_endpoints_is_declined_without_a_request(s3_handler, stubs):
    copied = await s3_handler.copy_server_side(
        SOURCE_KEY, "videos/R4/movie.mp4", _ignore_progress
    )

    assert copied is False


# Scenario: an empty object is declined
#   Given an object of 0 bytes in the bucket — there is no byte range to ask a part for
#   When copy_server_side is awaited
#   Then False is returned
#   And no multipart upload is created
async def test_an_empty_object_is_declined_without_starting_an_upload(s3_handler, stubs):
    _expect_head(stubs["R1"], SOURCE_KEY, 0)

    assert await s3_handler.copy_server_side(SOURCE_KEY, TARGET_KEY, _ignore_progress) is False


# -----------------------------------------------------------------------
# ------------------------------ failures -------------------------------
# -----------------------------------------------------------------------

# Scenario: a missing source is reported as missing
#   Given head_object answers 404 for the source key
#   When copy_server_side is awaited
#   Then FileNotFoundError is raised
#   And no multipart upload is created
async def test_a_missing_source_raises_file_not_found(s3_handler, stubs):
    stubs["R1"].add_client_error(
        "head_object", service_error_code="404", http_status_code=404,
        expected_params={"Bucket": "videos", "Key": SOURCE_KEY},
    )

    with pytest.raises(FileNotFoundError):
        await s3_handler.copy_server_side(SOURCE_KEY, TARGET_KEY, _ignore_progress)


# Scenario: a part that fails aborts the upload
#   Given a part size of 10 bytes and an object of 25 bytes
#   And the second upload_part_copy answers InternalError
#   When copy_server_side is awaited
#   Then the multipart upload is aborted
#   And the error is raised
#   And the upload is never completed, so nothing appears at the target key
async def test_a_failed_part_aborts_the_upload_and_raises(s3_handler, stubs):
    stub = stubs["R1"]
    _expect_head(stub, SOURCE_KEY, 25)
    _expect_upload_created(stub, TARGET_KEY)
    _expect_part(stub, SOURCE_KEY, TARGET_KEY, 1, "bytes=0-9")
    stub.add_client_error(
        "upload_part_copy", service_error_code="InternalError", http_status_code=500,
        expected_params=_part_params(SOURCE_KEY, TARGET_KEY, 2, "bytes=10-19"),
    )
    _expect_aborted(stub, TARGET_KEY)

    with pytest.raises(ClientError):
        await s3_handler.copy_server_side(SOURCE_KEY, TARGET_KEY, _ignore_progress)


# Scenario: a progress callback that raises stops the copy
#   Given a part size of 10 bytes and an object of 25 bytes
#   And a progress callback that raises after the first part — how a caller cancels
#   When copy_server_side is awaited
#   Then no further part is requested
#   And the multipart upload is aborted
#   And the callback's exception is raised unchanged
async def test_a_raising_progress_callback_aborts_the_upload(s3_handler, stubs):
    class Stop(Exception):
        pass

    def stop(copied: int) -> None:
        raise Stop()

    stub = stubs["R1"]
    _expect_head(stub, SOURCE_KEY, 25)
    _expect_upload_created(stub, TARGET_KEY)
    _expect_part(stub, SOURCE_KEY, TARGET_KEY, 1, "bytes=0-9")
    _expect_aborted(stub, TARGET_KEY)

    with pytest.raises(Stop):
        await s3_handler.copy_server_side(SOURCE_KEY, TARGET_KEY, stop)


# -----------------------------------------------------------------------
# ------------------------- other storage ------------------------------
# -----------------------------------------------------------------------

# Scenario: storage with no server-side copy declines
#   Given a local filesystem handler and a file on it
#   When copy_server_side is awaited to another path
#   Then False is returned
#   And nothing exists at the target path
async def test_local_storage_declines_a_server_side_copy(
    local_handler: LocalFSResourceHandler, local_resource_dir,
):
    source = str(local_resource_dir / "movie_a.mp4")
    target = local_resource_dir / "copy.mp4"

    assert await local_handler.copy_server_side(source, str(target), _ignore_progress) is False
    assert not target.exists()
