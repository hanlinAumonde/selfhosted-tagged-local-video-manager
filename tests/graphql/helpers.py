"""GraphQL document strings and assertion helpers used across test modules."""

from typing import Any


# -----------------------------------------------------------------------
# ------------------------------ Assertions ------------------------------
# -----------------------------------------------------------------------

def assert_no_errors(result) -> None:
    assert result.errors is None or result.errors == [], (
        f"Expected no GraphQL errors, got: {result.errors}"
    )


def assert_error_contains(result, fragment: str) -> None:
    """Assert that ``fragment`` appears in the error message or any wrapped cause.

    GraphQL surface error is ``error.message``,
    if the resolver re-raised one exception inside another (``raise X`` inside ``except Y``),
    the underlying cause sits on ``__context__`` / ``__cause__`` of ``error.original_error``,
    so we walk that chain too.
    """
    assert result.errors, "Expected GraphQL errors, got none"

    pieces: list[str] = []
    for e in result.errors:
        pieces.append(str(e.message))
        cur = getattr(e, "original_error", None)
        seen: set[int] = set()
        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))
            pieces.append(str(cur))
            cur = cur.__cause__ or cur.__context__

    messages = " | ".join(pieces)
    assert fragment in messages, (
        f"Expected error containing '{fragment}', got: {messages}"
    )


def first_error_message(result) -> str:
    assert result.errors, "Expected GraphQL errors, got none"
    return result.errors[0].message


# -----------------------------------------------------------------------
# ------------------------- Query documents -----------------------------
# -----------------------------------------------------------------------

GET_VIDEO_BY_ID = """
query GetVideoById($videoId: ID!) {
  getVideoById(videoId: $videoId) {
    id
    name
    isDir
    viewCount
    lastViewTime
    lastModifyTime
    introduction
    author
    loved
    size
    duration
    seriesName
    seriesOrder
    thumbnail
    isLocked
    tags { name count }
  }
}
"""


SEARCH_VIDEOS = """
query SearchVideos($input: VideoSearchInput!) {
  SearchVideos(input: $input) {
    pagination { size totalCount currentPageNumber }
    videos {
      id
      name
      author
      loved
      duration
      tags { name count }
    }
  }
}
"""


GET_TOP_TAGS = """
query GetTopTags {
  getTopTags { name count }
}
"""


GET_SUGGESTIONS = """
query GetSuggestions($input: SuggestionInput!) {
  getSuggestions(input: $input)
}
"""


BROWSE_DIRECTORY = """
query BrowseDirectory($input: RelativePathInput!) {
  browseDirectory(input: $input) {
    node { id name isDir size lastModifyTime }
  }
}
"""


SEARCH_IN_DIRECTORY = """
query SearchInDirectory($input: SearchInDirectoryInput!) {
  searchInDirectory(input: $input) {
    node { id name isDir size lastModifyTime relativePath isLocked }
  }
}
"""


GET_DIRECTORY_METADATA = """
query GetDirectoryMetadata($input: RelativePathInput!) {
  getDirectoryMetadata(input: $input) {
    totalSize
    lastModifiedTime
  }
}
"""


SEARCH_SERIES_BY_PREFIX = """
query SearchSeries($prefix: String!, $limit: Int!) {
  searchSeriesByPrefix(prefix: $prefix, limit: $limit)
}
"""


GET_SERIES_VIDEOS = """
query GetSeriesVideos($name: String!) {
  getSeriesVideos(name: $name) {
    id
    name
    seriesName
    seriesOrder
  }
}
"""


# -----------------------------------------------------------------------
# ------------------------- Mutation documents --------------------------
# -----------------------------------------------------------------------

UPDATE_VIDEO_METADATA = """
mutation UpdateVideoMetadata($input: UpdateVideoMetadataInput!) {
  updateVideoMetadata(input: $input) {
    success
    video {
      id
      name
      author
      introduction
      loved
      seriesName
      seriesOrder
      tags { name count }
    }
  }
}
"""


RECORD_VIDEO_VIEW = """
mutation RecordVideoView($videoId: ID!) {
  recordVideoView(videoId: $videoId) {
    success
    video { id viewCount lastViewTime }
  }
}
"""


DELETE_VIDEO = """
mutation DeleteVideo($videoId: ID!) {
  deleteVideo(videoId: $videoId) {
    success
    video { id }
  }
}
"""


CREATE_DIRECTORY = """
mutation CreateDirectory($input: CreateDirectoryInput!) {
  createDirectory(input: $input) {
    success
    name
    path
  }
}
"""


# -----------------------------------------------------------------------
# ----------------------- Subscription documents ------------------------
# -----------------------------------------------------------------------

BATCH_UPDATE_SUBSCRIPTION = """
subscription BatchUpdate($input: VideosBatchOperationInput!) {
  batchUpdateSubscription(input: $input) {
    status
    result { resultType message }
  }
}
"""


BATCH_DELETE_SUBSCRIPTION = """
subscription BatchDelete($input: VideosBatchOperationInput!) {
  batchDeleteSubscription(input: $input) {
    status
    result { resultType message }
  }
}
"""


# -----------------------------------------------------------------------
# ----------------------- Input builders --------------------------------
# -----------------------------------------------------------------------

def make_search_input(**overrides: Any) -> dict:
    base = {
        "titleKeyword": {"keyWord": None},
        "author": {"keyWord": None},
        "tags": [],
        "sortBy": "Latest",
        "fromPage": "SearchPage",
        "currentPageNumber": 1,
    }
    base.update(overrides)
    return base


def make_relative_path_input(
    relative_path: str | None = None,
    skip_cache: bool = False,
    recursive: bool = True,
) -> dict:
    return {
        "skipCache": skip_cache,
        "recursiveCalculation": recursive,
        "relativePath": relative_path,
    }


def make_search_in_directory_input(
    relative_path: str | None = "Test-category/Test-resource",
    *,
    name: str | None = None,
    author: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    return {
        "path": make_relative_path_input(relative_path=relative_path),
        "name": {"keyWord": name},
        "author": {"keyWord": author},
        "tags": list(tags or []),
    }


def make_create_directory_input(
    name: str = "new_folder", parent_relative_path: str | None = "Test-category/Test-resource",
) -> dict:
    return {
        "parentPath": make_relative_path_input(relative_path=parent_relative_path),
        "name": name,
    }


def make_update_input(video_id: str, **overrides: Any) -> dict:
    base: dict = {
        "videoId": video_id,
        "tags": [],
    }
    base.update(overrides)
    return base


MIGRATION_PREFLIGHT = """
mutation MigrationPreflight($input: MigrationPreflightInput!) {
  migrationPreflight(input: $input) {
    valid
    sourceFileSize
    conflictExists
    spaceAvailable
    spaceSufficient
    alreadyMigrating
    sameLocation
    errorMessage
  }
}
"""


CREATE_MIGRATION_TASK = """
mutation CreateMigrationTask($input: CreateMigrationTaskInput!) {
  createMigrationTask(input: $input) {
    success
    task {
      id
      sourcePath
      sourceCategory
      targetPath
      targetCategory
      fileName
      fileSize
      status
      conflictStrategy
      renamedTargetPath
    }
    errorMessage
  }
}
"""


CANCEL_MIGRATION_TASK = """
mutation CancelMigrationTask($input: MigrationTaskActionInput!) {
  cancelMigrationTask(input: $input) {
    success
    task {
      id
      status
    }
  }
}
"""


GET_MIGRATION_TASKS = """
query GetMigrationTasks($input: MigrationTaskQueryInput!) {
  getMigrationTasks(input: $input) {
    tasks {
      id
      sourcePath
      targetPath
      status
      fileName
      fileSize
    }
    totalCount
    page
    pageSize
  }
}
"""


MIGRATION_PROGRESS_SUBSCRIPTION = """
subscription MigrationProgress($input: MigrationTaskActionInput!) {
  migrationProgressSubscription(input: $input) {
    taskId
    status
    bytesTransferred
    totalBytes
    progressPercentage
    message
  }
}
"""


MIGRATION_RETRY_SUBSCRIPTION = """
subscription MigrationRetry($input: MigrationTaskActionInput!) {
  migrationRetrySubscription(input: $input) {
    taskId
    status
    bytesTransferred
    totalBytes
    progressPercentage
    message
  }
}
"""


def make_migration_path_input(relative_path: str) -> dict:
    return {"relativePath": relative_path}


def make_tags_operation(
    add: list[str] | None = None, remove: list[str] | None = None
) -> dict:
    """One batch tag edit, carrying both directions at once."""
    return {"addTags": list(add or []), "removeTags": list(remove or [])}


def make_batch_input(
    video_ids: list[str] | None = None,
    relative_path: str | None = None,
    *,
    tags_operation: dict | None = None,
    series_operation: dict | None = None,
    author: str | None = None,
    directory_deletion: str | None = None,
) -> dict:
    return {
        "videoIds": list(video_ids or []),
        "relativePath": make_relative_path_input(relative_path=relative_path),
        "tagsOperation": tags_operation,
        "seriesOperation": series_operation,
        "author": author,
        "directoryDeletion": directory_deletion,
    }
