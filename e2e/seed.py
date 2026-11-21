"""Lays out the resources the e2e journeys start from.

Runs once, as root, in the backend image before any backend process starts
(docker-compose.e2e.yml). It uses that image because it is the one under test and
already carries ffmpeg and boto3, so the seed needs nothing of its own.

Videos are generated rather than committed: no binaries in the repository, and the
same input on every run.

Each journey owns the directory named after it and touches nothing else, so journeys
can share one stack without resetting it between them.

Every directory needs a video in it: the file browser hides a directory that holds
none, unless a user created it in the app.
"""

import os
import subprocess
import time
from pathlib import Path

import boto3

RESOURCES = Path("/app/resources")
LOGS = Path("/app/logs")
# The uid/gid the backend image runs as (see Dockerfile).
APP_USER = 999

LAYOUT: dict[str, list[str]] = {
    "Local-resource/Resource-1": [
        "smoke/first.mp4",
        "smoke/second.mp4",
        "migration/traveller.mp4",
        "editing/postcard.mp4",
        "batch-tags/harbor.mp4",
        "batch-tags/lighthouse.mp4",
        "batch-tags/pier.mp4",
        "batch-delete/ferry.mp4",
        "batch-delete/dock.mp4",
        "batch-delete/buoy.mp4",
        "sync/letter.mp4",
    ],
    "Local-resource/Resource-2": [
        "migration/resident.mp4",
    ],
    "Local-resource/Resource-3": [],
}


def make_video(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=24",
            # Browsers only decode H.264 in yuv420p; faststart lets playback begin
            # before the whole file has arrived.
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(path),
        ],
        check=True,
    )


def create_bucket() -> None:
    """The backend expects the thumbnail bucket to exist; rustfs starts empty."""
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_RESOURCE_1_ENDPOINT_URL"],
        aws_access_key_id=os.environ["S3_RESOURCE_1_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_RESOURCE_1_SECRET_KEY"],
        region_name=os.environ["S3_RESOURCE_1_REGION"],
    )
    bucket = os.environ["S3_RESOURCE_1_BUCKET"]
    # rustfs has no healthcheck to wait on, so the first calls may land before it listens.
    for attempt in range(30):
        try:
            existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)
    if bucket not in existing:
        s3.create_bucket(Bucket=bucket)


def hand_over(root: Path) -> None:
    """Fresh volumes belong to root, but the backend runs as APP_USER and must be able
    to rename, delete and migrate what is there, and to write its logs."""
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [dirpath, *(os.path.join(dirpath, n) for n in dirnames + filenames)]:
            os.chown(name, APP_USER, APP_USER)


def main() -> None:
    for mount, videos in LAYOUT.items():
        (RESOURCES / mount).mkdir(parents=True, exist_ok=True)
        for video in videos:
            make_video(RESOURCES / mount / video)
    LOGS.mkdir(parents=True, exist_ok=True)
    hand_over(RESOURCES)
    hand_over(LOGS)
    create_bucket()
    print("seeded:", {mount: len(videos) for mount, videos in LAYOUT.items()})


if __name__ == "__main__":
    main()
