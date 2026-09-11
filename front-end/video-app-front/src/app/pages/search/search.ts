import { Component, inject, computed, effect, signal, DestroyRef } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { debounceTime, Subject, switchMap } from 'rxjs';
import { ActivatedRoute, Router } from '@angular/router';
import { FormBuilder, FormControl, FormsModule, ReactiveFormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { MatBadgeModule } from '@angular/material/badge';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatDialog } from '@angular/material/dialog';
import { map } from 'rxjs';
import { GqlService } from '../../services/GQL-service/GQL.service';
import { VideoCard } from '../../shared/components/video-card/video-card';
import { Pagination } from '../../shared/components/pagination/pagination';
import { VideoEditPanel } from '../../shared/components/video-edit-panel/video-edit-panel';
import { VideoEditPanelData } from '../../shared/models/panels.model';
import { SearchPageParam } from '../../shared/models/search.model';
import { SearchVideosDetail } from '../../shared/models/GQL-result.model';
import { SearchFrom, VideoSortOption, SearchField } from '../../core/graphql/generated/graphql';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { environment } from '../../../environments/environment';
import { PageStateService } from '../../services/Page-state-service/page-state.service';
import { ValidationService } from '../../services/validation-service/validation.service';
import { VideoUpdateEventService } from '../../services/video-update-event-service/video-update-event.service';
import { VideoUpdateType } from '../../shared/models/events.model';

@Component({
  selector: 'app-search',
  imports: [
    ReactiveFormsModule,
    FormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatSelectModule,
    MatBadgeModule,
    MatAutocompleteModule,
    MatProgressSpinnerModule,
    VideoCard,
    Pagination
],
  templateUrl: './search.html'
})
export class Search {
  private gqlService = inject(GqlService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private dialog = inject(MatDialog);
  private fb = inject(FormBuilder);
  private stateService = inject(PageStateService);
  private validationService = inject(ValidationService);
  private videoUpdateEventService = inject(VideoUpdateEventService);

  private updateSearchParamsAndForm(params: SearchPageParam) {
    this.searchParams.set({
        sortBy: params.sortBy ?? this.searchParams().sortBy,
        tags: params.tags ?? this.searchParams().tags,
        title: params.title ?? this.searchParams().title,
        author: params.author ?? this.searchParams().author
    });
    this.searchForm.patchValue({
        title: this.searchParams().title,
        author: this.searchParams().author
    });
  }

  private readonly INITIAL_SEARCH_RESULT: SearchVideosDetail = {
    videos: [],
    pagination: { size: 0, currentPageNumber: 0, totalCount: 0 }
  };

  private readonly DEFAULT_SEARCH_PARAMS: SearchPageParam = {
    sortBy: VideoSortOption.Latest,
    tags: [],
    title: '',
    author: ''
  };

  readonly sortOptions = [
    // "Latest" orders by lastViewTime, so it is spelled out: the option next to it
    // orders by the file's own mtime, and "Latest" alone reads as either.
    { value: VideoSortOption.Latest, label: 'Latest Viewed' },
    { value: VideoSortOption.LastUpdate, label: 'Last Updated' },
    { value: VideoSortOption.MostViewed, label: 'Most Viewed' },
    { value: VideoSortOption.Longest, label: 'Longest' },
    { value: VideoSortOption.Loved, label: 'Loved' },
  ];

  skeletonArray = [...Array(15).keys()];

  hasSearched = signal(false);

  searchParams = signal<SearchPageParam>(this.DEFAULT_SEARCH_PARAMS);

  searchForm = this.fb.group({
    title: [this.searchParams().title ?? '', [this.validationService.searchKeywordValidator()]],
    author: [this.searchParams().author ?? '', [this.validationService.searchKeywordValidator()]]
  });

  get title() { return this.searchForm.get('title') as FormControl<string>; }
  get author() { return this.searchForm.get('author') as FormControl<string>; }

  currentPage = toSignal(
    this.route.queryParams.pipe(
      map(params => {
        const page = parseInt(params['currentPageNumber'], 10);
        return (isNaN(page) || page < 1) ? 1 : page;
      })
    ),
    { initialValue: 1 }
  );

  titleSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(this.title.valueChanges, SearchField.Name),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  authorSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(this.author.valueChanges, SearchField.Author),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  searchTrigger = new Subject<SearchPageParam>();
  searchResults = toSignal(
    this.searchTrigger.asObservable().pipe(
      debounceTime(300),
      switchMap(params => 
        this.gqlService.searchVideosQuery(
          SearchFrom.SearchPage,
          params.sortBy,
          params.author ?? undefined,
          params.title ?? undefined,
          params.currentPage ?? 1,
          params.tags ?? []
        ).pipe(map(result => {
          if(params.checkPageBounds && !result.loading && result.data) {
            const pagination = result.data.pagination;
            if (pagination.size > 0) {
              const maxPage = Math.max(1, Math.ceil(pagination.totalCount / pagination.size));
              if (params.currentPage && params.currentPage > maxPage) {
                this.navigateToPage(maxPage);
              }
            }
          }
          return result;
        }))
      )
    ),
    { initialValue: this.gqlService.initialSignalData<SearchVideosDetail>(this.INITIAL_SEARCH_RESULT) }
  )

  selectedTagsCount = computed(() => this.searchParams().tags?.length ?? 0);

  totalPages = computed(() => {
    const pagination = this.searchResults().data?.pagination;
    if (!pagination || pagination.size === 0) return 0;
    return Math.ceil(pagination.totalCount / pagination.size);
  });

  constructor() {
    const hasStatePredicate = (state: SearchPageParam | undefined) => 
      state && (state.sortBy || state.tags?.length || state.title || state.author);

    const stateFound = [
      this.stateService.getState<SearchPageParam>(environment.searchpage_api + environment.refreshKey, false),
      history.state as SearchPageParam | undefined,
      this.stateService.getState<SearchPageParam>(environment.searchpage_api, true)
    ].find(hasStatePredicate);

    const urlParams = new URLSearchParams(window.location.search);
    const hasUrlParams = urlParams.has('currentPageNumber');

    if (stateFound) {
      this.updateSearchParamsAndForm(stateFound);
      this.hasSearched.set(true);
    }else if (hasUrlParams) {
      // immediately execute search with existing parameters in page state
      this.hasSearched.set(true);
    }

    effect(() => {
      const params = this.searchParams();
      if (this.hasSearched()) {
        this.searchTrigger.next({ 
          ...params, 
          checkPageBounds: false, 
          currentPage: this.currentPage(),
        });
      }
    });

    this.videoUpdateEventService.onEvent()
      .pipe(takeUntilDestroyed())
      .subscribe(event => {
        if (this.hasSearched()) {
          const currentVideos = this.searchResults().data?.videos;
          // For update events, only refresh if current results contain affected videos
          if (event.type === VideoUpdateType.Updated) {
            const ids = new Set(event.videoIds);
            const affected = currentVideos?.some(v => ids.has(v.id)) ?? false;
            if (affected) {
              this.searchTrigger.next({ 
                ...this.searchParams(), 
                checkPageBounds: false, 
                currentPage: this.currentPage(), 
              });
            }
            return;
          }
          // For delete events, always re-execute since pagination may shift
          this.searchTrigger.next({ 
            ...this.searchParams(),
            checkPageBounds: false, 
            currentPage: this.currentPage() 
          });
        }
      });
  }

  private navigateToPage(page?:number) {
    this.router.navigate([environment.searchpage_api], {
      queryParams: { currentPageNumber: page ?? this.currentPage() },
    });
  }

  onSearch() {
    if (this.searchForm.invalid) return;

    const formValue = this.searchForm.value;
    const newParams: SearchPageParam = {
      ...this.searchParams(),
      title: formValue.title ?? '',
      author: formValue.author ?? ''
    };
    this.updateSearchParamsAndForm(newParams);

    if (!this.hasSearched()) {
      this.hasSearched.set(true);
    }
    this.navigateToPage(1);
  }

  clearInput(field: "title" | "author") {
    if (field === "title") {
      this.updateSearchForm({title: ''});
    } else if (field === "author") {
      this.updateSearchForm({author: ''});
    }
  }

  updateSearchForm(searchFormInputs: {title?: string, author?: string}) {
    this.searchForm.patchValue({ 
      title: searchFormInputs.title ?? this.searchParams().title, 
      author: searchFormInputs.author ?? this.searchParams().author 
    });
  }

  onSortChange(sortBy: VideoSortOption) {
    const newParams: SearchPageParam = { ...this.searchParams(), sortBy };
    this.updateSearchParamsAndForm(newParams);
    //when sort by loved, the total count may change
    if(sortBy === VideoSortOption.Loved) {
      this.navigateToPage(1);
    }
  }

  openTagFilter() {
    const dialogRef = this.dialog.open(VideoEditPanel, {
      width: '500px',
      data: {
        mode: 'filter',
        selectedTags: this.searchParams().tags ?? []
      } as VideoEditPanelData
    });

    dialogRef.afterClosed().subscribe((result: string[] | undefined) => {
      if (result !== undefined) {
        const newParams: SearchPageParam = { ...this.searchParams(), tags: result };
        this.updateSearchParamsAndForm(newParams);
        this.navigateToPage(1);
      }
    });
  }

  onPageChange(page: number) {
    this.navigateToPage(page);
  }
}