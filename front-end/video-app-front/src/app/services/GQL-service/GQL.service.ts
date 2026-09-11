import { inject, Injectable } from '@angular/core';
import {
  GetSuggestionsGQL,
  GetTopTagsAsSuggestionGQL,
  GetTopTagsGQL,
  GetVideoByIdGQL,
  SearchVideosGQL,
  RecordVideoViewGQL,
  QueryGetSuggestionsArgs,
  SearchField,
  UpdateVideoMetadataGQL,
  VideoSearchInput,
  SearchFrom,
  VideoSortOption,
  BrowseDirectoryGQL,
  SearchInDirectoryGQL,
  CreateDirectoryGQL,
  DeleteVideoGQL,
  VideosBatchOperationInput,
  GetDirectoryMetadataGQL,
  BatchUpdateSubscriptionGQL,
  BatchDeleteSubscriptionGQL,
  SearchSeriesByPrefixGQL,
  GetSeriesVideosGQL,
  SeriesFieldInput,
  SeriesOperationInput,
  MigrationPreflightGQL,
  MigrationPreflightInput,
  CreateMigrationTaskGQL,
  CreateMigrationTaskInput,
  CancelMigrationTaskGQL,
  MigrationTaskActionInput,
  GetMigrationTasksGQL,
  MigrationTaskQueryInput,
  MigrationProgressGQL,
  MigrationRetryGQL,
} from '../../core/graphql/generated/graphql';
import {
  catchError,
  debounceTime,
  distinctUntilChanged,
  map,
  Observable,
  of,
  switchMap,
  tap
} from 'rxjs';
import { ObservableQuery } from '@apollo/client';
import { DeepPartial } from '@apollo/client/utilities';
import {
  BatchUpdateVideosDetail,
  BrowseDirectoryDetail,
  CancelMigrationTaskDetail,
  CreateDirectoryDetail,
  CreateMigrationTaskDetail,
  DeleteVideoDetail,
  DirectoryMetadataDetail,
  GetTopTagsDetail,
  MigrationPreflightDetail,
  MigrationProgressDetail,
  MigrationTaskListDetail,
  ResultState,
  SearchVideosDetail,
  SeriesVideosDetail,
  VideoDetail,
  VideoMutationDetail,
  VideoRecordViewDetail
} from '../../shared/models/GQL-result.model';
import { Apollo } from 'apollo-angular';
import { ValidationService } from '../validation-service/validation.service';
import { ToastService } from '../toast-service/toast.service';
import { ToastType } from '../../shared/models/toast.model';

@Injectable({
  providedIn: 'root',
})
export class GqlService {
  private getSuggestionsGQL = inject(GetSuggestionsGQL)
  private getTopTagsAsSuggestionGQL = inject(GetTopTagsAsSuggestionGQL)
  private getTopTagsGQL = inject(GetTopTagsGQL)
  private getVideoByIdGQL = inject(GetVideoByIdGQL)
  private searchVideosGQL = inject(SearchVideosGQL)
  private recordVideoViewGQL = inject(RecordVideoViewGQL)
  private updateVideoMetadataGQL = inject(UpdateVideoMetadataGQL)
  private browseDirectoryGQL = inject(BrowseDirectoryGQL)
  private searchInDirectoryGQL = inject(SearchInDirectoryGQL)
  private deleteVideoGQL = inject(DeleteVideoGQL)
  private createDirectoryGQL = inject(CreateDirectoryGQL)
  private getDirectoryMetadataGQL = inject(GetDirectoryMetadataGQL)
  private batchUpdateVideosSubscriptionGQL = inject(BatchUpdateSubscriptionGQL)
  private batchDeleteVideosSubscriptionGQL = inject(BatchDeleteSubscriptionGQL)
  private searchSeriesByPrefixGQL = inject(SearchSeriesByPrefixGQL)
  private getSeriesVideosGQL = inject(GetSeriesVideosGQL)
  private migrationPreflightGQL = inject(MigrationPreflightGQL)
  private createMigrationTaskGQL = inject(CreateMigrationTaskGQL)
  private cancelMigrationTaskGQL = inject(CancelMigrationTaskGQL)
  private getMigrationTasksGQL = inject(GetMigrationTasksGQL)
  private migrationProgressGQL = inject(MigrationProgressGQL)
  private migrationRetryGQL = inject(MigrationRetryGQL)
  private validationService = inject(ValidationService);
  private toastService = inject(ToastService);

  private filterUndefinedResult<T>(result : T[]){
    return result.filter((r) => r != undefined)
  }

  initialSignalData<T>(data: T): ResultState<T> {
    return {
      loading: true,
      error: null,
      data: data
    } 
  }

  private toResultStateObservable<TData, TResult>(
    gqlObservable: Observable<ObservableQuery.Result<TData, "empty" | "complete" | "streaming" | "partial"> | Apollo.MutateResult<TData>>,
    dataExtractor: (data: NonNullable<TData> | NonNullable<DeepPartial<TData>>) => TResult | null,
    isWatchQuery: boolean = true,
  ): Observable<ResultState<TResult>> {
    return gqlObservable.pipe(
        map(result => ({
          loading: isWatchQuery? (result.loading ?? true) : false,
          error: result.error?.message ?? null,
          data: result.data ? dataExtractor(result.data) : null
        })),
        catchError((error) => {
          return of<ResultState<TResult>>({
            loading: false,
            error: error.message ?? 'An unknown error occurred',
            data: null
          });
        }),
        tap(result => {
          if(result.error){
            this.toastService.emitNewToast(`Failed GraphQL request: ${result.error}`, ToastType.Error);
          }
        })
        
      )
  }

  // ----------------------------Query----------------------------

  private getTopTagsAsSuggestionQuery(): Observable<ResultState<string[]>>{
    return this.toResultStateObservable(
      this.getTopTagsAsSuggestionGQL.fetch(),
      (data) => {
        return this.filterUndefinedResult(
          this.filterUndefinedResult(data?.getTopTags ?? []).map(tag => tag.name)
        );
      },
      false
    )
  }

  getSuggestionsQuery(formValueChanges: Observable<string | null>, field: SearchField): Observable<ResultState<string[]>> {
    return formValueChanges.pipe(
      this.validationService.filterValidInput(field),
      debounceTime(500),
      distinctUntilChanged(),
      switchMap(keyword => 
        (!keyword || keyword.length < 1)? 
        (field === SearchField.Tag? this.getTopTagsAsSuggestionQuery() : of(this.initialSignalData<string[]>([]))) 
        :
        this.toResultStateObservable(
          this.getSuggestionsGQL.fetch({
            variables: {
              input: {
                keyword: {
                  keyWord: keyword
                },
                suggestionType: field
              }
            } as QueryGetSuggestionsArgs
          }),
          (data) => this.filterUndefinedResult(data?.getSuggestions ?? []),
          false
        )        
      )
    )
  }

  getTopTagsQuery(limit? : number): Observable<ResultState<GetTopTagsDetail>> {
    return this.toResultStateObservable(
      this.getTopTagsGQL.fetch(),
      (data) => {
        const tags = this.filterUndefinedResult(
          this.filterUndefinedResult(data?.getTopTags ?? [])
            .filter(tag => tag.name && tag.count)
        ) as GetTopTagsDetail;
        return limit ? tags.slice(0, limit) : tags;
      },
      false
    )
  }
  
  searchVideosQuery(fromPage: SearchFrom,sortBy?: VideoSortOption, author?: string, title?: string,
                    currentPageNumber: number = 1, tags: string[] = []): Observable<ResultState<SearchVideosDetail>> {
    const input = {
      author: { keyWord: author ?? undefined },
      currentPageNumber: currentPageNumber,
      fromPage: fromPage,
      sortBy: sortBy,
      tags: tags,
      titleKeyword: { keyWord: title ?? undefined },
    } as VideoSearchInput;
    return this.toResultStateObservable(
      this.searchVideosGQL.watch({ variables: { input: input }}).valueChanges,
      (data) => ({
        pagination: data.SearchVideos?.pagination ?? { size: 0, currentPageNumber: 0, totalCount: 0 },
        videos: this.filterUndefinedResult(data.SearchVideos?.videos ?? [])
      } as SearchVideosDetail)
    )
  }

  getVideoByIdQuery(videoId: string): Observable<ResultState<VideoDetail | null>> {
    return this.toResultStateObservable(
      this.getVideoByIdGQL.watch({ variables: { videoId } }).valueChanges,
      (data) => (data.getVideoById ?? null) as VideoDetail | null
    )
  }

  browseDirectoryQuery(relativePath?: string, 
                       skipCache: boolean = false, 
                       recursiveCalculation: boolean = true): Observable<ResultState<BrowseDirectoryDetail>> {
    return this.toResultStateObservable(
      this.browseDirectoryGQL.watch({
        variables: { 
          input: { 
            relativePath: relativePath,
            skipCache: skipCache,
            recursiveCalculation: recursiveCalculation
          } 
        }
      }).valueChanges,
      (data) => this.filterUndefinedResult(data.browseDirectory ?? []) as BrowseDirectoryDetail
    )
  }

  /**
   * Search the catalogued videos under a directory and everything below it.
   *
   * A one-shot fetch rather than a watch query: a search is something the user asks for,
   * not a view that should re-run itself.
   */
  searchInDirectoryQuery(relativePath: string,
                         name?: string,
                         author?: string,
                         tags: string[] = []): Observable<ResultState<BrowseDirectoryDetail>> {
    return this.toResultStateObservable(
      this.searchInDirectoryGQL.fetch({
        variables: {
          input: {
            path: { relativePath: relativePath },
            name: { keyWord: name || undefined },
            author: { keyWord: author || undefined },
            tags: tags
          }
        }
      }),
      (data) => this.filterUndefinedResult(data.searchInDirectory ?? []) as BrowseDirectoryDetail,
      false
    )
  }

  getDirectoryMetadataQuery(relativePath?: string): Observable<ResultState<DirectoryMetadataDetail>> {
    return this.toResultStateObservable(
      this.getDirectoryMetadataGQL.fetch({
        variables: { input: { relativePath: relativePath } }
      }),
      (data) => ({
        totalSize: data.getDirectoryMetadata?.totalSize ?? 0,
        lastModifiedTime: data.getDirectoryMetadata?.lastModifiedTime ?? ''
      } as DirectoryMetadataDetail),
      false
    )
  }

  searchSeriesByPrefixQuery(prefix: string, limit: number): Observable<ResultState<string[]>> {
    return this.toResultStateObservable(
      this.searchSeriesByPrefixGQL.fetch({ variables: { prefix: prefix ?? '', limit } }),
      (data) => this.filterUndefinedResult(data?.searchSeriesByPrefix ?? []),
      false
    )
  }

  getSeriesVideosQuery(name: string): Observable<ResultState<SeriesVideosDetail>> {
    return this.toResultStateObservable(
      this.getSeriesVideosGQL.watch({ variables: { name } }).valueChanges,
      (data) => this.filterUndefinedResult(data?.getSeriesVideos ?? []) as SeriesVideosDetail
    )
  }

  // ----------------------------Mutation----------------------------

  recordVideoViewMutation(videoId: string): Observable<ResultState<VideoRecordViewDetail>> {
    return this.toResultStateObservable(
      this.recordVideoViewGQL.mutate({ variables: { videoId } }),
      (data) => ({
        success: data.recordVideoView?.success ?? false,
        video: data.recordVideoView?.video
      } as VideoRecordViewDetail)
    )
  }

  deleteVideoMutation(videoId: string): Observable<ResultState<DeleteVideoDetail>> {
    return this.toResultStateObservable(
      this.deleteVideoGQL.mutate({ variables: { videoId } }),
      (data) => ({
        success: data.deleteVideo?.success ?? false,
        video: data.deleteVideo?.video
      } as DeleteVideoDetail)
    )
  }

  createDirectoryMutation(parentPath: string | undefined, name: string): Observable<ResultState<CreateDirectoryDetail>> {
    return this.toResultStateObservable(
      this.createDirectoryGQL.mutate({
        variables: {
          input: {
            parentPath: { relativePath: parentPath },
            name: name
          }
        }
      }),
      (data) => (data.createDirectory ?? null) as CreateDirectoryDetail | null,
      false
    )
  }

  updateVideoMetadataMutation(videoID: string,loved: boolean = false,tags?: string[],
                              title?: string,description?: string,author?: string,
                              series?: SeriesFieldInput): Observable<ResultState<VideoMutationDetail>>{
    return this.toResultStateObservable(this.updateVideoMetadataGQL.mutate({
          variables: {
            input: {
              videoId: videoID,
              name: title,
              introduction: description,
              tags: tags ?? [],
              author: author,
              loved: loved,
              series: series,
            }
          }
        }
      ),
      (data) => ({
        success: data.updateVideoMetadata?.success ?? false,
        video: data.updateVideoMetadata?.video ?? null
      } as VideoMutationDetail)
    )
  }

  // ----------------------------Subscription----------------------------

  private batchOperationDataConverter(subscriptionResult: any): BatchUpdateVideosDetail {
    return {
      result: {
        resultType: subscriptionResult?.result?.resultType ?? undefined,
        message: subscriptionResult?.result?.message ?? undefined
      },
      status: subscriptionResult?.status ?? undefined
    } as BatchUpdateVideosDetail
  }

  batchUpdateVideosSubscription(input: VideosBatchOperationInput){
    return this.toResultStateObservable(
      this.batchUpdateVideosSubscriptionGQL.subscribe({
        variables: {
          input: {
            videoIds: input.videoIds,
            relativePath: input.relativePath,
            tagsOperation: input.tagsOperation ?? undefined,
            author: input.author ?? undefined,
            seriesOperation: input.seriesOperation ?? undefined,
          }
        }
      }),
      (data) => this.batchOperationDataConverter(data.batchUpdateSubscription)
    )
  }

  batchDeleteVideosSubscription(input: VideosBatchOperationInput){
    return this.toResultStateObservable(
      this.batchDeleteVideosSubscriptionGQL.subscribe({
        variables: {
          input: {
            videoIds: input.videoIds,
            relativePath: input.relativePath
          }
        }
      }),
      (data) => this.batchOperationDataConverter(data.batchDeleteSubscription)
    )
  }

  // ----------------------------Migration----------------------------

  migrationPreflightMutation(input: MigrationPreflightInput) {
    return this.toResultStateObservable(
      this.migrationPreflightGQL.mutate({ variables: { input } }),
      (data) => (data.migrationPreflight ?? null) as MigrationPreflightDetail | null,
      false
    )
  }

  createMigrationTaskMutation(input: CreateMigrationTaskInput) {
    return this.toResultStateObservable(
      this.createMigrationTaskGQL.mutate({ variables: { input } }),
      (data) => (data.createMigrationTask ?? null) as CreateMigrationTaskDetail | null,
      false
    )
  }

  cancelMigrationTaskMutation(input: MigrationTaskActionInput) {
    return this.toResultStateObservable(
      this.cancelMigrationTaskGQL.mutate({ variables: { input } }),
      (data) => (data.cancelMigrationTask ?? null) as CancelMigrationTaskDetail | null,
      false
    )
  }

  getMigrationTasksQuery(input: MigrationTaskQueryInput) {
    return this.toResultStateObservable(
      this.getMigrationTasksGQL.fetch({ variables: { input } }),
      (data) => (data.getMigrationTasks ?? null) as MigrationTaskListDetail | null,
      false
    )
  }

  migrationProgressSubscription(input: MigrationTaskActionInput) {
    return this.toResultStateObservable(
      this.migrationProgressGQL.subscribe({ variables: { input } }),
      (data) => (data.migrationProgressSubscription ?? null) as MigrationProgressDetail | null
    )
  }

  migrationRetrySubscription(input: MigrationTaskActionInput) {
    return this.toResultStateObservable(
      this.migrationRetryGQL.subscribe({ variables: { input } }),
      (data) => (data.migrationRetrySubscription ?? null) as MigrationProgressDetail | null
    )
  }
}
