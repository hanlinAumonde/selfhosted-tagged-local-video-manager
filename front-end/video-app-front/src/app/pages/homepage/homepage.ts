import { Component, inject } from '@angular/core';
import { VideoCard } from '../../shared/components/video-card/video-card';
import { MatButtonModule } from '@angular/material/button';
import { GqlService } from '../../services/GQL-service/GQL.service';
import { Router, RouterModule } from '@angular/router';
import {
  SearchFrom,
  VideoSortOption
} from '../../core/graphql/generated/graphql';
import { SearchPageParam } from '../../shared/models/search.model';
import { environment } from '../../../environments/environment';
import { PageStateService } from '../../services/Page-state-service/page-state.service';
import { VideoUpdateEventService } from '../../services/video-update-event-service/video-update-event.service';
import { GetTopTagsDetail, ResultState, SearchVideosDetail } from '../../shared/models/GQL-result.model';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { filter, Subject, switchMap } from 'rxjs';

@Component({
  selector: 'app-homepage',
  imports: [VideoCard, MatButtonModule, RouterModule],
  templateUrl: './homepage.html',
})
export class Homepage {
  private gqlService = inject(GqlService);
  private router = inject(Router);
  private stateService = inject(PageStateService);
  private videoUpdateEventService = inject(VideoUpdateEventService);

  private readonly INITIAL_VIDEOS_SEARCH_RESULT : SearchVideosDetail = {
    videos: [],
    pagination: {
      size: 0,
      currentPageNumber: 0,
      totalCount: 0
    }
  }

  private SearchTrigger = new Subject<VideoSortOption>();
  private tagsTrigger = new Subject<void>();

  private triggerObservable(category: VideoSortOption) {
    return this.SearchTrigger.asObservable().pipe(
      filter(triggerCategory => triggerCategory === category)
    );
  }

  searchPageApi = environment.searchpage_api;

  // Loved Videos
  lovedVideos = toSignal(
    this.triggerObservable(VideoSortOption.Loved).pipe(
      switchMap(() => this.gqlService.searchVideosQuery(SearchFrom.FrontalPage, VideoSortOption.Loved))
    ),
    { initialValue: this.gqlService.initialSignalData<SearchVideosDetail>(this.INITIAL_VIDEOS_SEARCH_RESULT) }
  );

  // Latest Viewed
  latestViewedVideos = toSignal(
    this.triggerObservable(VideoSortOption.Latest).pipe(
      switchMap(() => this.gqlService.searchVideosQuery(SearchFrom.FrontalPage, VideoSortOption.Latest))
    ),
    { initialValue: this.gqlService.initialSignalData<SearchVideosDetail>(this.INITIAL_VIDEOS_SEARCH_RESULT) }
  );

  // Last Updated — newest on disk, which is not the same rail as Latest Viewed:
  // a file added months ago can be the one watched most recently, and vice versa.
  lastUpdatedVideos = toSignal(
    this.triggerObservable(VideoSortOption.LastUpdate).pipe(
      switchMap(() => this.gqlService.searchVideosQuery(SearchFrom.FrontalPage, VideoSortOption.LastUpdate))
    ),
    { initialValue: this.gqlService.initialSignalData<SearchVideosDetail>(this.INITIAL_VIDEOS_SEARCH_RESULT) }
  );

  // Most Viewed
  mostViewedVideos = toSignal(
    this.triggerObservable(VideoSortOption.MostViewed).pipe(
      switchMap(() => this.gqlService.searchVideosQuery(SearchFrom.FrontalPage, VideoSortOption.MostViewed))
    ),
    { initialValue: this.gqlService.initialSignalData<SearchVideosDetail>(this.INITIAL_VIDEOS_SEARCH_RESULT) }
  );

  // Top Tags
  topTags = toSignal(
    this.tagsTrigger.asObservable().pipe(
      switchMap(() => this.gqlService.getTopTagsQuery())
    ),
    { initialValue: this.gqlService.initialSignalData<GetTopTagsDetail>([]) }
  );

  constructor() {
    this.SearchTrigger.next(VideoSortOption.Loved);
    this.SearchTrigger.next(VideoSortOption.Latest);
    this.SearchTrigger.next(VideoSortOption.LastUpdate);
    this.SearchTrigger.next(VideoSortOption.MostViewed);
    this.tagsTrigger.next();

    this.videoUpdateEventService.onEvent()
      .pipe(takeUntilDestroyed())
      .subscribe(event => {
        const ids = new Set(event.videoIds);

        const sectionContainsAffectedId = (section: ResultState<SearchVideosDetail>) =>
          section.data?.videos.some(v => ids.has(v.id)) ?? false;

        if (sectionContainsAffectedId(this.lovedVideos())) {
          this.SearchTrigger.next(VideoSortOption.Loved);
        }
        if (sectionContainsAffectedId(this.latestViewedVideos())) {
          this.SearchTrigger.next(VideoSortOption.Latest);
        }
        if (sectionContainsAffectedId(this.lastUpdatedVideos())) {
          this.SearchTrigger.next(VideoSortOption.LastUpdate);
        }
        if (sectionContainsAffectedId(this.mostViewedVideos())) {
          this.SearchTrigger.next(VideoSortOption.MostViewed);
        }

        this.tagsTrigger.next();
      });
  }

  OnMoreClick(section: 'loved' | 'latest' | 'lastUpdate' | 'mostViewed'){
    const option = () => {
      switch(section){
        case 'loved': return VideoSortOption.Loved;
        case 'latest': return VideoSortOption.Latest;
        case 'lastUpdate': return VideoSortOption.LastUpdate;
        case 'mostViewed': return VideoSortOption.MostViewed;
        default: { return VideoSortOption.Loved; }
      }
    }
    this.stateService.clearState(environment.searchpage_api + environment.refreshKey, false);
    this.router.navigate([environment.searchpage_api], {
      state: { sortBy: option() } as SearchPageParam,
      queryParams: { currentPageNumber: 1 }
    });
  }

  tagState(tagName: string): SearchPageParam {
    return { tags: [tagName] };
  }

  onTagClick(tagName: string) {
    this.stateService.setState<SearchPageParam>(environment.searchpage_api, { tags: [tagName] }, true);
  }
}
