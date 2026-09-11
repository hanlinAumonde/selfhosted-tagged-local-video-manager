import { gql } from 'apollo-angular';
import { Injectable } from '@angular/core';
import * as Apollo from 'apollo-angular';
export type Maybe<T> = T | null;
export type InputMaybe<T> = Maybe<T>;
export type Exact<T extends { [key: string]: unknown }> = { [K in keyof T]: T[K] };
export type MakeOptional<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]?: Maybe<T[SubKey]> };
export type MakeMaybe<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]: Maybe<T[SubKey]> };
export type MakeEmpty<T extends { [key: string]: unknown }, K extends keyof T> = { [_ in K]?: never };
export type Incremental<T> = T | { [P in keyof T]?: P extends ' $fragmentName' | '__typename' ? T[P] : never };
/** All built-in and custom scalars, mapped to their actual values */
export type Scalars = {
  ID: { input: string; output: string; }
  String: { input: string; output: string; }
  Boolean: { input: boolean; output: boolean; }
  Int: { input: number; output: number; }
  Float: { input: number; output: number; }
  /** A large integer that may exceed GraphQL's 32-bit Int limit. Serialized as a string. */
  BigInt: { input: string; output: string; }
};

export type BatchOperationStatus = {
  __typename?: 'BatchOperationStatus';
  result?: Maybe<VideosBatchOperationResult>;
  status?: Maybe<Scalars['String']['output']>;
};

export enum BatchResultType {
  AlreadyUpToDate = 'AlreadyUpToDate',
  Failure = 'Failure',
  PartialSuccess = 'PartialSuccess',
  Success = 'Success'
}

export type CreateDirectoryInput = {
  name: Scalars['String']['input'];
  parentPath: RelativePathInput;
};

export type CreateMigrationTaskInput = {
  conflictStrategy?: InputMaybe<Scalars['String']['input']>;
  sourceVideoId: Scalars['String']['input'];
  targetDirRelativePath: RelativePathInput;
};

export type DirectoryMetadataResult = {
  __typename?: 'DirectoryMetadataResult';
  lastModifiedTime: Scalars['Float']['output'];
  totalSize: Scalars['Float']['output'];
};

export type DirectoryMutationResult = {
  __typename?: 'DirectoryMutationResult';
  name: Scalars['String']['output'];
  path: Scalars['String']['output'];
  success: Scalars['Boolean']['output'];
};

export type FileBrowseNode = {
  __typename?: 'FileBrowseNode';
  node: Video;
};

export type MigrationPreflightInput = {
  sourceVideoId: Scalars['String']['input'];
  targetDirRelativePath: RelativePathInput;
};

export type MigrationPreflightResult = {
  __typename?: 'MigrationPreflightResult';
  alreadyMigrating: Scalars['Boolean']['output'];
  conflictExists: Scalars['Boolean']['output'];
  errorMessage?: Maybe<Scalars['String']['output']>;
  sameLocation: Scalars['Boolean']['output'];
  sourceFileSize: Scalars['BigInt']['output'];
  spaceAvailable?: Maybe<Scalars['BigInt']['output']>;
  spaceSufficient?: Maybe<Scalars['Boolean']['output']>;
  valid: Scalars['Boolean']['output'];
};

export type MigrationProgressStatus = {
  __typename?: 'MigrationProgressStatus';
  bytesTransferred: Scalars['BigInt']['output'];
  message?: Maybe<Scalars['String']['output']>;
  progressPercentage: Scalars['Float']['output'];
  status: MigrationStatusEnum;
  taskId: Scalars['String']['output'];
  totalBytes: Scalars['BigInt']['output'];
};

export enum MigrationStatusEnum {
  Cancelled = 'CANCELLED',
  Completed = 'COMPLETED',
  DbUpdated = 'DB_UPDATED',
  DeletingSource = 'DELETING_SOURCE',
  Failed = 'FAILED',
  Pending = 'PENDING',
  Processing = 'PROCESSING',
  ProcessDone = 'PROCESS_DONE',
  UpdatingDb = 'UPDATING_DB'
}

export type MigrationTask = {
  __typename?: 'MigrationTask';
  bytesTransferred: Scalars['BigInt']['output'];
  completedAt?: Maybe<Scalars['Float']['output']>;
  conflictStrategy?: Maybe<Scalars['String']['output']>;
  createdAt: Scalars['Float']['output'];
  errorMessage?: Maybe<Scalars['String']['output']>;
  failedStep?: Maybe<Scalars['String']['output']>;
  fileName: Scalars['String']['output'];
  fileSize: Scalars['BigInt']['output'];
  id: Scalars['ID']['output'];
  renamedTargetPath?: Maybe<Scalars['String']['output']>;
  sourceCategory: Scalars['String']['output'];
  sourcePath: Scalars['String']['output'];
  status: MigrationStatusEnum;
  targetCategory: Scalars['String']['output'];
  targetPath: Scalars['String']['output'];
  updatedAt: Scalars['Float']['output'];
};

export type MigrationTaskActionInput = {
  taskId: Scalars['String']['input'];
};

export type MigrationTaskListResult = {
  __typename?: 'MigrationTaskListResult';
  page: Scalars['Int']['output'];
  pageSize: Scalars['Int']['output'];
  tasks: Array<MigrationTask>;
  totalCount: Scalars['Int']['output'];
};

export type MigrationTaskMutationResult = {
  __typename?: 'MigrationTaskMutationResult';
  errorMessage?: Maybe<Scalars['String']['output']>;
  success: Scalars['Boolean']['output'];
  task?: Maybe<MigrationTask>;
};

export type MigrationTaskQueryInput = {
  page?: Scalars['Int']['input'];
  pageSize?: Scalars['Int']['input'];
  statusFilter?: InputMaybe<Array<Scalars['String']['input']>>;
};

export type Mutation = {
  __typename?: 'Mutation';
  cancelMigrationTask: MigrationTaskMutationResult;
  createDirectory: DirectoryMutationResult;
  createMigrationTask: MigrationTaskMutationResult;
  deleteVideo: VideoMutationResult;
  migrationPreflight: MigrationPreflightResult;
  recordVideoView: VideoMutationResult;
  updateVideoMetadata: VideoMutationResult;
};


export type MutationCancelMigrationTaskArgs = {
  input: MigrationTaskActionInput;
};


export type MutationCreateDirectoryArgs = {
  input: CreateDirectoryInput;
};


export type MutationCreateMigrationTaskArgs = {
  input: CreateMigrationTaskInput;
};


export type MutationDeleteVideoArgs = {
  videoId: Scalars['ID']['input'];
};


export type MutationMigrationPreflightArgs = {
  input: MigrationPreflightInput;
};


export type MutationRecordVideoViewArgs = {
  videoId: Scalars['ID']['input'];
};


export type MutationUpdateVideoMetadataArgs = {
  input: UpdateVideoMetadataInput;
};

export type Pagination = {
  __typename?: 'Pagination';
  currentPageNumber: Scalars['Int']['output'];
  size: Scalars['Int']['output'];
  totalCount: Scalars['Int']['output'];
};

export type Query = {
  __typename?: 'Query';
  SearchVideos: VideoSearchResult;
  browseDirectory: Array<FileBrowseNode>;
  getDirectoryMetadata: DirectoryMetadataResult;
  getMigrationTasks: MigrationTaskListResult;
  getSeriesVideos: Array<Video>;
  getSuggestions: Array<Scalars['String']['output']>;
  getTopTags: Array<VideoTag>;
  getVideoById: Video;
  searchInDirectory: Array<FileBrowseNode>;
  searchSeriesByPrefix: Array<Scalars['String']['output']>;
};


export type QuerySearchVideosArgs = {
  input: VideoSearchInput;
};


export type QueryBrowseDirectoryArgs = {
  input: RelativePathInput;
};


export type QueryGetDirectoryMetadataArgs = {
  input: RelativePathInput;
};


export type QueryGetMigrationTasksArgs = {
  input: MigrationTaskQueryInput;
};


export type QueryGetSeriesVideosArgs = {
  name: Scalars['String']['input'];
};


export type QueryGetSuggestionsArgs = {
  input: SuggestionInput;
};


export type QueryGetVideoByIdArgs = {
  videoId: Scalars['ID']['input'];
};


export type QuerySearchInDirectoryArgs = {
  input: SearchInDirectoryInput;
};


export type QuerySearchSeriesByPrefixArgs = {
  limit: Scalars['Int']['input'];
  prefix: Scalars['String']['input'];
};

export type RelativePathInput = {
  parsedPath?: InputMaybe<Array<Scalars['String']['input']>>;
  recursiveCalculation?: Scalars['Boolean']['input'];
  relativePath?: InputMaybe<Scalars['String']['input']>;
  skipCache?: Scalars['Boolean']['input'];
};

export enum SearchField {
  Author = 'Author',
  Name = 'Name',
  Tag = 'Tag'
}

export enum SearchFrom {
  FrontalPage = 'FrontalPage',
  SearchPage = 'SearchPage'
}

export type SearchInDirectoryInput = {
  author: SerachKeyword;
  name: SerachKeyword;
  path: RelativePathInput;
  tags?: Array<Scalars['String']['input']>;
};

export type SerachKeyword = {
  keyWord?: InputMaybe<Scalars['String']['input']>;
};

export type SeriesFieldInput = {
  clear?: Scalars['Boolean']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
  orders?: Array<SeriesOrderEntryInput>;
};

export type SeriesOperationInput = {
  clear?: Scalars['Boolean']['input'];
  name?: InputMaybe<Scalars['String']['input']>;
  orders?: Array<SeriesOrderEntryInput>;
};

export type SeriesOrderEntryInput = {
  order: Scalars['Int']['input'];
  videoId: Scalars['String']['input'];
};

export type Subscription = {
  __typename?: 'Subscription';
  batchDeleteSubscription: BatchOperationStatus;
  batchUpdateSubscription: BatchOperationStatus;
  migrationProgressSubscription: MigrationProgressStatus;
  migrationRetrySubscription: MigrationProgressStatus;
};


export type SubscriptionBatchDeleteSubscriptionArgs = {
  input: VideosBatchOperationInput;
};


export type SubscriptionBatchUpdateSubscriptionArgs = {
  input: VideosBatchOperationInput;
};


export type SubscriptionMigrationProgressSubscriptionArgs = {
  input: MigrationTaskActionInput;
};


export type SubscriptionMigrationRetrySubscriptionArgs = {
  input: MigrationTaskActionInput;
};

export type SuggestionInput = {
  keyword: SerachKeyword;
  suggestionType: SearchField;
};

export type TagsOperationMappingInput = {
  append: Scalars['Boolean']['input'];
  tags: Array<Scalars['String']['input']>;
};

export type UpdateVideoMetadataInput = {
  author?: InputMaybe<Scalars['String']['input']>;
  introduction?: InputMaybe<Scalars['String']['input']>;
  loved?: InputMaybe<Scalars['Boolean']['input']>;
  name?: InputMaybe<Scalars['String']['input']>;
  series?: InputMaybe<SeriesFieldInput>;
  tags: Array<Scalars['String']['input']>;
  videoId: Scalars['String']['input'];
};

export type Video = {
  __typename?: 'Video';
  author: Scalars['String']['output'];
  duration: Scalars['Float']['output'];
  id: Scalars['ID']['output'];
  introduction: Scalars['String']['output'];
  isDir: Scalars['Boolean']['output'];
  isLocked: Scalars['Boolean']['output'];
  lastModifyTime: Scalars['Float']['output'];
  lastViewTime: Scalars['Float']['output'];
  loved: Scalars['Boolean']['output'];
  name: Scalars['String']['output'];
  relativePath?: Maybe<Scalars['String']['output']>;
  seriesName?: Maybe<Scalars['String']['output']>;
  seriesOrder?: Maybe<Scalars['Int']['output']>;
  size: Scalars['Float']['output'];
  tags: Array<VideoTag>;
  thumbnail?: Maybe<Scalars['String']['output']>;
  viewCount: Scalars['Int']['output'];
};

export type VideoMutationResult = {
  __typename?: 'VideoMutationResult';
  success: Scalars['Boolean']['output'];
  video?: Maybe<Video>;
};

export type VideoSearchInput = {
  author: SerachKeyword;
  currentPageNumber?: InputMaybe<Scalars['Int']['input']>;
  fromPage: SearchFrom;
  sortBy: VideoSortOption;
  tags: Array<Scalars['String']['input']>;
  titleKeyword: SerachKeyword;
};

export type VideoSearchResult = {
  __typename?: 'VideoSearchResult';
  pagination: Pagination;
  videos: Array<Video>;
};

export enum VideoSortOption {
  LastUpdate = 'LastUpdate',
  Latest = 'Latest',
  Longest = 'Longest',
  Loved = 'Loved',
  MostViewed = 'MostViewed'
}

export type VideoTag = {
  __typename?: 'VideoTag';
  count: Scalars['Int']['output'];
  name: Scalars['String']['output'];
};

export type VideosBatchOperationInput = {
  author?: InputMaybe<Scalars['String']['input']>;
  relativePath: RelativePathInput;
  seriesOperation?: InputMaybe<SeriesOperationInput>;
  tagsOperation?: InputMaybe<TagsOperationMappingInput>;
  videoIds: Array<Scalars['String']['input']>;
};

export type VideosBatchOperationResult = {
  __typename?: 'VideosBatchOperationResult';
  message?: Maybe<Scalars['String']['output']>;
  resultType: BatchResultType;
};

export type MigrationPreflightMutationVariables = Exact<{
  input: MigrationPreflightInput;
}>;


export type MigrationPreflightMutation = { __typename?: 'Mutation', migrationPreflight: { __typename?: 'MigrationPreflightResult', valid: boolean, sourceFileSize: string, conflictExists: boolean, spaceAvailable?: string | null, spaceSufficient?: boolean | null, alreadyMigrating: boolean, sameLocation: boolean, errorMessage?: string | null } };

export type CreateMigrationTaskMutationVariables = Exact<{
  input: CreateMigrationTaskInput;
}>;


export type CreateMigrationTaskMutation = { __typename?: 'Mutation', createMigrationTask: { __typename?: 'MigrationTaskMutationResult', success: boolean, errorMessage?: string | null, task?: { __typename?: 'MigrationTask', id: string, sourcePath: string, sourceCategory: string, targetPath: string, targetCategory: string, fileName: string, fileSize: string, bytesTransferred: string, status: MigrationStatusEnum, errorMessage?: string | null, failedStep?: string | null, conflictStrategy?: string | null, renamedTargetPath?: string | null, createdAt: number, updatedAt: number, completedAt?: number | null } | null } };

export type CancelMigrationTaskMutationVariables = Exact<{
  input: MigrationTaskActionInput;
}>;


export type CancelMigrationTaskMutation = { __typename?: 'Mutation', cancelMigrationTask: { __typename?: 'MigrationTaskMutationResult', success: boolean, errorMessage?: string | null, task?: { __typename?: 'MigrationTask', id: string, sourcePath: string, targetPath: string, fileName: string, status: MigrationStatusEnum } | null } };

export type GetMigrationTasksQueryVariables = Exact<{
  input: MigrationTaskQueryInput;
}>;


export type GetMigrationTasksQuery = { __typename?: 'Query', getMigrationTasks: { __typename?: 'MigrationTaskListResult', totalCount: number, page: number, pageSize: number, tasks: Array<{ __typename?: 'MigrationTask', id: string, sourcePath: string, sourceCategory: string, targetPath: string, targetCategory: string, fileName: string, fileSize: string, bytesTransferred: string, status: MigrationStatusEnum, errorMessage?: string | null, failedStep?: string | null, conflictStrategy?: string | null, renamedTargetPath?: string | null, createdAt: number, updatedAt: number, completedAt?: number | null }> } };

export type MigrationProgressSubscriptionVariables = Exact<{
  input: MigrationTaskActionInput;
}>;


export type MigrationProgressSubscription = { __typename?: 'Subscription', migrationProgressSubscription: { __typename?: 'MigrationProgressStatus', taskId: string, status: MigrationStatusEnum, bytesTransferred: string, totalBytes: string, progressPercentage: number, message?: string | null } };

export type MigrationRetrySubscriptionVariables = Exact<{
  input: MigrationTaskActionInput;
}>;


export type MigrationRetrySubscription = { __typename?: 'Subscription', migrationRetrySubscription: { __typename?: 'MigrationProgressStatus', taskId: string, status: MigrationStatusEnum, bytesTransferred: string, totalBytes: string, progressPercentage: number, message?: string | null } };

export type UpdateVideoMetadataMutationVariables = Exact<{
  input: UpdateVideoMetadataInput;
}>;


export type UpdateVideoMetadataMutation = { __typename?: 'Mutation', updateVideoMetadata: { __typename?: 'VideoMutationResult', success: boolean, video?: { __typename?: 'Video', id: string, name: string, author: string, loved: boolean, introduction: string, seriesName?: string | null, seriesOrder?: number | null, tags: Array<{ __typename?: 'VideoTag', name: string }> } | null } };

export type RecordVideoViewMutationVariables = Exact<{
  videoId: Scalars['ID']['input'];
}>;


export type RecordVideoViewMutation = { __typename?: 'Mutation', recordVideoView: { __typename?: 'VideoMutationResult', success: boolean, video?: { __typename?: 'Video', id: string, viewCount: number, lastViewTime: number } | null } };

export type CreateDirectoryMutationVariables = Exact<{
  input: CreateDirectoryInput;
}>;


export type CreateDirectoryMutation = { __typename?: 'Mutation', createDirectory: { __typename?: 'DirectoryMutationResult', success: boolean, name: string, path: string } };

export type DeleteVideoMutationVariables = Exact<{
  videoId: Scalars['ID']['input'];
}>;


export type DeleteVideoMutation = { __typename?: 'Mutation', deleteVideo: { __typename?: 'VideoMutationResult', success: boolean, video?: { __typename?: 'Video', id: string } | null } };

export type SearchVideosQueryVariables = Exact<{
  input: VideoSearchInput;
}>;


export type SearchVideosQuery = { __typename?: 'Query', SearchVideos: { __typename?: 'VideoSearchResult', pagination: { __typename?: 'Pagination', size: number, totalCount: number, currentPageNumber: number }, videos: Array<{ __typename?: 'Video', id: string, name: string, author: string, viewCount: number, loved: boolean, lastViewTime: number, lastModifyTime: number, thumbnail?: string | null, duration: number, isLocked: boolean }> } };

export type GetTopTagsQueryVariables = Exact<{ [key: string]: never; }>;


export type GetTopTagsQuery = { __typename?: 'Query', getTopTags: Array<{ __typename?: 'VideoTag', name: string, count: number }> };

export type GetTopTagsAsSuggestionQueryVariables = Exact<{ [key: string]: never; }>;


export type GetTopTagsAsSuggestionQuery = { __typename?: 'Query', getTopTags: Array<{ __typename?: 'VideoTag', name: string }> };

export type GetVideoByIdQueryVariables = Exact<{
  videoId: Scalars['ID']['input'];
}>;


export type GetVideoByIdQuery = { __typename?: 'Query', getVideoById: { __typename?: 'Video', id: string, name: string, author: string, viewCount: number, loved: boolean, lastViewTime: number, lastModifyTime: number, introduction: string, duration: number, seriesName?: string | null, seriesOrder?: number | null, isLocked: boolean, tags: Array<{ __typename?: 'VideoTag', name: string }> } };

export type SearchSeriesByPrefixQueryVariables = Exact<{
  prefix: Scalars['String']['input'];
  limit: Scalars['Int']['input'];
}>;


export type SearchSeriesByPrefixQuery = { __typename?: 'Query', searchSeriesByPrefix: Array<string> };

export type GetSeriesVideosQueryVariables = Exact<{
  name: Scalars['String']['input'];
}>;


export type GetSeriesVideosQuery = { __typename?: 'Query', getSeriesVideos: Array<{ __typename?: 'Video', id: string, name: string, seriesOrder?: number | null, thumbnail?: string | null, duration: number, isLocked: boolean }> };

export type GetSuggestionsQueryVariables = Exact<{
  input: SuggestionInput;
}>;


export type GetSuggestionsQuery = { __typename?: 'Query', getSuggestions: Array<string> };

export type BrowseDirectoryQueryVariables = Exact<{
  input: RelativePathInput;
}>;


export type BrowseDirectoryQuery = { __typename?: 'Query', browseDirectory: Array<{ __typename?: 'FileBrowseNode', node: { __typename?: 'Video', id: string, isDir: boolean, name: string, author: string, loved: boolean, lastModifyTime: number, introduction: string, size: number, duration: number, seriesName?: string | null, seriesOrder?: number | null, isLocked: boolean, relativePath?: string | null, tags: Array<{ __typename?: 'VideoTag', name: string }> } }> };

export type SearchInDirectoryQueryVariables = Exact<{
  input: SearchInDirectoryInput;
}>;


export type SearchInDirectoryQuery = { __typename?: 'Query', searchInDirectory: Array<{ __typename?: 'FileBrowseNode', node: { __typename?: 'Video', id: string, isDir: boolean, name: string, author: string, loved: boolean, lastModifyTime: number, introduction: string, size: number, duration: number, seriesName?: string | null, seriesOrder?: number | null, isLocked: boolean, relativePath?: string | null, tags: Array<{ __typename?: 'VideoTag', name: string }> } }> };

export type GetDirectoryMetadataQueryVariables = Exact<{
  input: RelativePathInput;
}>;


export type GetDirectoryMetadataQuery = { __typename?: 'Query', getDirectoryMetadata: { __typename?: 'DirectoryMetadataResult', totalSize: number, lastModifiedTime: number } };

export type BatchUpdateSubscriptionSubscriptionVariables = Exact<{
  input: VideosBatchOperationInput;
}>;


export type BatchUpdateSubscriptionSubscription = { __typename?: 'Subscription', batchUpdateSubscription: { __typename?: 'BatchOperationStatus', status?: string | null, result?: { __typename?: 'VideosBatchOperationResult', resultType: BatchResultType, message?: string | null } | null } };

export type BatchDeleteSubscriptionSubscriptionVariables = Exact<{
  input: VideosBatchOperationInput;
}>;


export type BatchDeleteSubscriptionSubscription = { __typename?: 'Subscription', batchDeleteSubscription: { __typename?: 'BatchOperationStatus', status?: string | null, result?: { __typename?: 'VideosBatchOperationResult', resultType: BatchResultType, message?: string | null } | null } };

export const MigrationPreflightDocument = gql`
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
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class MigrationPreflightGQL extends Apollo.Mutation<MigrationPreflightMutation, MigrationPreflightMutationVariables> {
    override document = MigrationPreflightDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const CreateMigrationTaskDocument = gql`
    mutation CreateMigrationTask($input: CreateMigrationTaskInput!) {
  createMigrationTask(input: $input) {
    success
    errorMessage
    task {
      id
      sourcePath
      sourceCategory
      targetPath
      targetCategory
      fileName
      fileSize
      bytesTransferred
      status
      errorMessage
      failedStep
      conflictStrategy
      renamedTargetPath
      createdAt
      updatedAt
      completedAt
    }
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class CreateMigrationTaskGQL extends Apollo.Mutation<CreateMigrationTaskMutation, CreateMigrationTaskMutationVariables> {
    override document = CreateMigrationTaskDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const CancelMigrationTaskDocument = gql`
    mutation CancelMigrationTask($input: MigrationTaskActionInput!) {
  cancelMigrationTask(input: $input) {
    success
    errorMessage
    task {
      id
      sourcePath
      targetPath
      fileName
      status
    }
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class CancelMigrationTaskGQL extends Apollo.Mutation<CancelMigrationTaskMutation, CancelMigrationTaskMutationVariables> {
    override document = CancelMigrationTaskDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const GetMigrationTasksDocument = gql`
    query GetMigrationTasks($input: MigrationTaskQueryInput!) {
  getMigrationTasks(input: $input) {
    totalCount
    page
    pageSize
    tasks {
      id
      sourcePath
      sourceCategory
      targetPath
      targetCategory
      fileName
      fileSize
      bytesTransferred
      status
      errorMessage
      failedStep
      conflictStrategy
      renamedTargetPath
      createdAt
      updatedAt
      completedAt
    }
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class GetMigrationTasksGQL extends Apollo.Query<GetMigrationTasksQuery, GetMigrationTasksQueryVariables> {
    override document = GetMigrationTasksDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const MigrationProgressDocument = gql`
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
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class MigrationProgressGQL extends Apollo.Subscription<MigrationProgressSubscription, MigrationProgressSubscriptionVariables> {
    override document = MigrationProgressDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const MigrationRetryDocument = gql`
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
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class MigrationRetryGQL extends Apollo.Subscription<MigrationRetrySubscription, MigrationRetrySubscriptionVariables> {
    override document = MigrationRetryDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const UpdateVideoMetadataDocument = gql`
    mutation UpdateVideoMetadata($input: UpdateVideoMetadataInput!) {
  updateVideoMetadata(input: $input) {
    success
    video {
      id
      name
      tags {
        name
      }
      author
      loved
      introduction
      seriesName
      seriesOrder
    }
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class UpdateVideoMetadataGQL extends Apollo.Mutation<UpdateVideoMetadataMutation, UpdateVideoMetadataMutationVariables> {
    override document = UpdateVideoMetadataDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const RecordVideoViewDocument = gql`
    mutation RecordVideoView($videoId: ID!) {
  recordVideoView(videoId: $videoId) {
    success
    video {
      id
      viewCount
      lastViewTime
    }
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class RecordVideoViewGQL extends Apollo.Mutation<RecordVideoViewMutation, RecordVideoViewMutationVariables> {
    override document = RecordVideoViewDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const CreateDirectoryDocument = gql`
    mutation CreateDirectory($input: CreateDirectoryInput!) {
  createDirectory(input: $input) {
    success
    name
    path
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class CreateDirectoryGQL extends Apollo.Mutation<CreateDirectoryMutation, CreateDirectoryMutationVariables> {
    override document = CreateDirectoryDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const DeleteVideoDocument = gql`
    mutation DeleteVideo($videoId: ID!) {
  deleteVideo(videoId: $videoId) {
    success
    video {
      id
    }
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class DeleteVideoGQL extends Apollo.Mutation<DeleteVideoMutation, DeleteVideoMutationVariables> {
    override document = DeleteVideoDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const SearchVideosDocument = gql`
    query SearchVideos($input: VideoSearchInput!) {
  SearchVideos(input: $input) {
    pagination {
      size
      totalCount
      currentPageNumber
    }
    videos {
      id
      name
      author
      viewCount
      loved
      lastViewTime
      lastModifyTime
      thumbnail
      duration
      isLocked
    }
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class SearchVideosGQL extends Apollo.Query<SearchVideosQuery, SearchVideosQueryVariables> {
    override document = SearchVideosDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const GetTopTagsDocument = gql`
    query GetTopTags {
  getTopTags {
    name
    count
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class GetTopTagsGQL extends Apollo.Query<GetTopTagsQuery, GetTopTagsQueryVariables> {
    override document = GetTopTagsDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const GetTopTagsAsSuggestionDocument = gql`
    query GetTopTagsAsSuggestion {
  getTopTags {
    name
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class GetTopTagsAsSuggestionGQL extends Apollo.Query<GetTopTagsAsSuggestionQuery, GetTopTagsAsSuggestionQueryVariables> {
    override document = GetTopTagsAsSuggestionDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const GetVideoByIdDocument = gql`
    query GetVideoById($videoId: ID!) {
  getVideoById(videoId: $videoId) {
    id
    name
    tags {
      name
    }
    author
    viewCount
    loved
    lastViewTime
    lastModifyTime
    introduction
    duration
    seriesName
    seriesOrder
    isLocked
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class GetVideoByIdGQL extends Apollo.Query<GetVideoByIdQuery, GetVideoByIdQueryVariables> {
    override document = GetVideoByIdDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const SearchSeriesByPrefixDocument = gql`
    query SearchSeriesByPrefix($prefix: String!, $limit: Int!) {
  searchSeriesByPrefix(prefix: $prefix, limit: $limit)
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class SearchSeriesByPrefixGQL extends Apollo.Query<SearchSeriesByPrefixQuery, SearchSeriesByPrefixQueryVariables> {
    override document = SearchSeriesByPrefixDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const GetSeriesVideosDocument = gql`
    query GetSeriesVideos($name: String!) {
  getSeriesVideos(name: $name) {
    id
    name
    seriesOrder
    thumbnail
    duration
    isLocked
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class GetSeriesVideosGQL extends Apollo.Query<GetSeriesVideosQuery, GetSeriesVideosQueryVariables> {
    override document = GetSeriesVideosDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const GetSuggestionsDocument = gql`
    query GetSuggestions($input: SuggestionInput!) {
  getSuggestions(input: $input)
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class GetSuggestionsGQL extends Apollo.Query<GetSuggestionsQuery, GetSuggestionsQueryVariables> {
    override document = GetSuggestionsDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const BrowseDirectoryDocument = gql`
    query BrowseDirectory($input: RelativePathInput!) {
  browseDirectory(input: $input) {
    node {
      id
      isDir
      name
      tags {
        name
      }
      author
      loved
      lastModifyTime
      introduction
      size
      duration
      seriesName
      seriesOrder
      isLocked
      relativePath
    }
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class BrowseDirectoryGQL extends Apollo.Query<BrowseDirectoryQuery, BrowseDirectoryQueryVariables> {
    override document = BrowseDirectoryDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const SearchInDirectoryDocument = gql`
    query SearchInDirectory($input: SearchInDirectoryInput!) {
  searchInDirectory(input: $input) {
    node {
      id
      isDir
      name
      tags {
        name
      }
      author
      loved
      lastModifyTime
      introduction
      size
      duration
      seriesName
      seriesOrder
      isLocked
      relativePath
    }
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class SearchInDirectoryGQL extends Apollo.Query<SearchInDirectoryQuery, SearchInDirectoryQueryVariables> {
    override document = SearchInDirectoryDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const GetDirectoryMetadataDocument = gql`
    query GetDirectoryMetadata($input: RelativePathInput!) {
  getDirectoryMetadata(input: $input) {
    totalSize
    lastModifiedTime
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class GetDirectoryMetadataGQL extends Apollo.Query<GetDirectoryMetadataQuery, GetDirectoryMetadataQueryVariables> {
    override document = GetDirectoryMetadataDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const BatchUpdateSubscriptionDocument = gql`
    subscription BatchUpdateSubscription($input: VideosBatchOperationInput!) {
  batchUpdateSubscription(input: $input) {
    result {
      resultType
      message
    }
    status
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class BatchUpdateSubscriptionGQL extends Apollo.Subscription<BatchUpdateSubscriptionSubscription, BatchUpdateSubscriptionSubscriptionVariables> {
    override document = BatchUpdateSubscriptionDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }
export const BatchDeleteSubscriptionDocument = gql`
    subscription BatchDeleteSubscription($input: VideosBatchOperationInput!) {
  batchDeleteSubscription(input: $input) {
    result {
      resultType
      message
    }
    status
  }
}
    `;

  @Injectable({
    providedIn: 'root'
  })
  export class BatchDeleteSubscriptionGQL extends Apollo.Subscription<BatchDeleteSubscriptionSubscription, BatchDeleteSubscriptionSubscriptionVariables> {
    override document = BatchDeleteSubscriptionDocument;
    
    constructor(apollo: Apollo.Apollo) {
      super(apollo);
    }
  }