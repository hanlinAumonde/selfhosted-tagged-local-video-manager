import strawberry
from src.schema.types.fileBrowse_type import FileBrowseNode
from src.schema.types.migration_type import MigrationTaskListResult
from src.schema.types.search_type import (
    DirectoryMetadataResult,
    VideoSearchResult,
)
from src.resolvers import query_resolver, migration_resolver
from src.schema.types.video_type import Video, VideoTag


@strawberry.type
class Query:
    SearchVideos: VideoSearchResult = strawberry.field(resolver=query_resolver.resolve_search_videos)

    getTopTags: list[VideoTag] = strawberry.field(resolver=query_resolver.resolve_get_top_tags)

    getSuggestions: list[str] = strawberry.field(resolver=query_resolver.resolve_get_suggestions)

    getVideoById: Video = strawberry.field(resolver=query_resolver.resolve_get_video_by_id)

    browseDirectory: list[FileBrowseNode] = strawberry.field(resolver=query_resolver.resolve_browse_directory)

    searchInDirectory: list[FileBrowseNode] = strawberry.field(resolver=query_resolver.resolve_search_in_directory)

    getDirectoryMetadata: DirectoryMetadataResult = strawberry.field(resolver=query_resolver.resolve_directory_metadata)

    searchSeriesByPrefix: list[str] = strawberry.field(resolver=query_resolver.resolve_search_series_by_prefix)

    getSeriesVideos: list[Video] = strawberry.field(resolver=query_resolver.resolve_get_series_videos)

    getMigrationTasks: MigrationTaskListResult = strawberry.field(resolver=migration_resolver.resolve_get_migration_tasks)
