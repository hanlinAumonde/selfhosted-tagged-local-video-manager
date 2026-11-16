import {
    BatchUpdateSubscriptionSubscription,
    BrowseDirectoryQuery,
    CancelMigrationBatchMutation,
    CancelMigrationTaskMutation,
    CreateMigrationBatchMutation,
    CreateDirectoryMutation,
    CreateMigrationTaskMutation,
    DeleteVideoMutation,
    GetDirectoryMetadataQuery,
    GetMigrationTasksQuery,
    GetSeriesVideosQuery,
    GetTopTagsQuery,
    GetVideoByIdQuery,
    MigrationBatchPreflightMutation,
    MigrationBatchProgressSubscription,
    MigrationPreflightMutation,
    MigrationProgressSubscription,
    RecordVideoViewMutation,
    SearchVideosQuery,
    UpdateVideoMetadataMutation
} from "../../core/graphql/generated/graphql";

export interface ResultState<T> {
    loading: boolean;
    error: string | null
    data: T | null;
}

export type VideoDetail = GetVideoByIdQuery['getVideoById'];

export type GetTopTagsDetail = GetTopTagsQuery['getTopTags'];

export type SearchVideosDetail = SearchVideosQuery['SearchVideos'];
export type SearchedVideo = SearchVideosQuery['SearchVideos']['videos'][0];

export type VideoMutationDetail = UpdateVideoMetadataMutation['updateVideoMetadata'];

export type VideoRecordViewDetail = RecordVideoViewMutation['recordVideoView'];

export type BrowseDirectoryDetail = BrowseDirectoryQuery['browseDirectory'];
export type FileBrowseNode = BrowseDirectoryQuery['browseDirectory'][0];
export type BrowsedVideo = BrowseDirectoryQuery['browseDirectory'][0]['node'];

export type DeleteVideoDetail = DeleteVideoMutation['deleteVideo'];

export type CreateDirectoryDetail = CreateDirectoryMutation['createDirectory'];

export type BatchUpdateVideosDetail = BatchUpdateSubscriptionSubscription['batchUpdateSubscription'];

export type DirectoryMetadataDetail = GetDirectoryMetadataQuery['getDirectoryMetadata'];

export type SeriesVideosDetail = GetSeriesVideosQuery['getSeriesVideos'];
export type SeriesVideoItem = GetSeriesVideosQuery['getSeriesVideos'][0];

export type MigrationPreflightDetail = MigrationPreflightMutation['migrationPreflight'];
export type CreateMigrationTaskDetail = CreateMigrationTaskMutation['createMigrationTask'];
export type CancelMigrationTaskDetail = CancelMigrationTaskMutation['cancelMigrationTask'];
export type MigrationTaskListDetail = GetMigrationTasksQuery['getMigrationTasks'];
export type MigrationTaskItem = MigrationTaskListDetail['tasks'][0];
export type MigrationProgressDetail = MigrationProgressSubscription['migrationProgressSubscription'];

export type MigrationBatchPreflightDetail = MigrationBatchPreflightMutation['migrationBatchPreflight'];
export type MigrationBatchPreflightItem = MigrationBatchPreflightDetail['items'][0];
export type CreateMigrationBatchDetail = CreateMigrationBatchMutation['createMigrationBatch'];
export type MigrationBatchSummaryDetail = CancelMigrationBatchMutation['cancelMigrationBatch'];
export type MigrationBatchProgressDetail = MigrationBatchProgressSubscription['migrationBatchProgress'];