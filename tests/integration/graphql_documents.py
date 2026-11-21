# -----------------------------------------------------------------------
# GraphQL documents
# -----------------------------------------------------------------------

BROWSE_DIRECTORY = """
query BrowseDirectory($input: RelativePathInput!) {
  browseDirectory(input: $input) {
    node { id name isDir size lastModifyTime duration author tags { name count } isLocked }
  }
}
"""

SEARCH_VIDEOS = """
query SearchVideos($input: VideoSearchInput!) {
  SearchVideos(input: $input) {
    pagination { size totalCount currentPageNumber }
    videos { id name author loved duration tags { name count } seriesName seriesOrder }
  }
}
"""

GET_VIDEO_BY_ID = """
query GetVideoById($videoId: ID!) {
  getVideoById(videoId: $videoId) {
    id name author loved introduction tags { name count }
    viewCount lastViewTime duration seriesName seriesOrder isLocked
  }
}
"""

UPDATE_VIDEO_METADATA = """
mutation UpdateVideoMetadata($input: UpdateVideoMetadataInput!) {
  updateVideoMetadata(input: $input) {
    success
    video { id name author loved introduction tags { name count } seriesName seriesOrder }
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

GET_TOP_TAGS = """
query GetTopTags {
  getTopTags { name count }
}
"""

SEARCH_SERIES_BY_PREFIX = """
query SearchSeries($prefix: String!, $limit: Int!) {
  searchSeriesByPrefix(prefix: $prefix, limit: $limit)
}
"""

GET_SERIES_VIDEOS = """
query GetSeriesVideos($name: String!) {
  getSeriesVideos(name: $name) { id name seriesName seriesOrder }
}
"""

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
# Migration
# -----------------------------------------------------------------------

CREATE_MIGRATION_TASK = """
mutation CreateMigrationTask($input: CreateMigrationTaskInput!) {
  createMigrationTask(input: $input) {
    success
    task { id status }
    errorMessage
  }
}
"""

CANCEL_MIGRATION_TASK = """
mutation CancelMigrationTask($input: MigrationTaskActionInput!) {
  cancelMigrationTask(input: $input) {
    success
    task { id status }
  }
}
"""

GET_MIGRATION_TASKS = """
query GetMigrationTasks($input: MigrationTaskQueryInput!) {
  getMigrationTasks(input: $input) {
    tasks { id fileName status batchId }
    totalCount
  }
}
"""

MIGRATION_PROGRESS_SUBSCRIPTION = """
subscription MigrationProgress($input: MigrationTaskActionInput!) {
  migrationProgressSubscription(input: $input) {
    taskId status bytesTransferred totalBytes
  }
}
"""

CREATE_MIGRATION_BATCH = """
mutation CreateMigrationBatch($input: CreateMigrationBatchInput!) {
  createMigrationBatch(input: $input) {
    batchId
    tasks { id fileName status }
    skipped { sourceVideoId reason }
  }
}
"""

_BATCH_SUMMARY_FIELDS = "batchId total active completed failed cancelled"

CANCEL_MIGRATION_BATCH = f"""
mutation CancelMigrationBatch($input: MigrationBatchActionInput!) {{
  cancelMigrationBatch(input: $input) {{ {_BATCH_SUMMARY_FIELDS} }}
}}
"""

MIGRATION_BATCH_PROGRESS = f"""
subscription MigrationBatchProgress($input: MigrationBatchActionInput!) {{
  migrationBatchProgress(input: $input) {{
    summary {{ {_BATCH_SUMMARY_FIELDS} }}
    task {{ taskId status }}
  }}
}}
"""


# -----------------------------------------------------------------------
# Browsing: folders and search inside a directory
# -----------------------------------------------------------------------

CREATE_DIRECTORY = """
mutation CreateDirectory($input: CreateDirectoryInput!) {
  createDirectory(input: $input) { success name path }
}
"""

SEARCH_IN_DIRECTORY = """
query SearchInDirectory($input: SearchInDirectoryInput!) {
  searchInDirectory(input: $input) {
    node { id name isDir relativePath }
  }
}
"""
