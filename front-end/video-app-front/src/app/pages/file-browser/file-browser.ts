import { Component, inject, signal, computed, effect, OnDestroy, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { GqlService } from '../../services/GQL-service/GQL.service';
import {
  BrowseDirectoryDetail,
  FileBrowseNode,
} from '../../shared/models/GQL-result.model';
import { BatchPanelVideoItem, DirectorySearchCriteria } from '../../shared/models/panels.model';
import { PageStateService } from '../../services/Page-state-service/page-state.service';
import { environment } from '../../../environments/environment';
import {
  SortCriterion,
  ManagementRefreshState,
  comparatorBySortOption
} from '../../shared/models/management.model';
import { BottomToolbar } from '../../shared/components/bottom-toolbar/bottom-toolbar';
import { FileBrowseTable } from '../../shared/components/file-browse-table/file-browse-table';
import { ToastService } from '../../services/toast-service/toast.service';
import { PathHistoryService } from '../../services/path-history-service/path-history.service';
import { VideoUpdateEventService } from '../../services/video-update-event-service/video-update-event.service';
import { MigrationTrackerService } from '../../services/migration-tracker-service/migration-tracker.service';
import { VideoUpdateEvent } from '../../shared/models/events.model';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { merge, Subscription } from 'rxjs';
import { ToastType } from '../../shared/models/toast.model';

@Component({
  selector: 'app-file-browser',
  imports: [
    BottomToolbar,
    FileBrowseTable
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './file-browser.html'
})
export class FileBrowser implements OnDestroy{
  private gqlService = inject(GqlService);
  private stateService = inject(PageStateService);
  private toastService = inject(ToastService);
  private destroyRef = inject(DestroyRef);

  private videoUpdateEventService = inject(VideoUpdateEventService);
  private migrationTracker = inject(MigrationTrackerService);
  pathHistoryService = inject(PathHistoryService)

  tableWidth = signal<number>(0);
  sortCriteria = signal<SortCriterion>({
    index: 0,
    order: true
  });
  currentPath = signal<string[]>([]);
  directoryContents = signal(this.gqlService.initialSignalData<BrowseDirectoryDetail>([]));
  selectedIds = signal<Set<string>>(new Set());

  private directorySubscription: Subscription | null = null;

  /**
   * What is on screen. Null means the table is showing the directory listing; anything
   * else means it is showing the results of that search, taken over the current directory
   * and everything below it.
   */
  searchCriteria = signal<DirectorySearchCriteria | null>(null);
  isSearching = computed(() => this.searchCriteria() !== null);
  searchSummary = computed<string[]>(() => {
    const criteria = this.searchCriteria();
    if (!criteria) return [];
    return [
      ...(criteria.name ? [`name: ${criteria.name}`] : []),
      ...(criteria.author ? [`author: ${criteria.author}`] : []),
      ...criteria.tags.map(tag => `tag: ${tag}`)
    ];
  });

  isAtRoot = computed(() => this.currentPath().length === 0);
  selectedCount = computed(() => this.selectedIds().size);
  hasSelection = computed(() => this.selectedIds().size > 0);
  selectedVideoItems = computed<ReadonlyArray<BatchPanelVideoItem>>(() => {
    const ids = this.selectedIds();
    const contents = this.directoryContents().data;
    if (!contents || ids.size === 0) return [];
    return contents
      .filter(item => !item.node.isDir && ids.has(item.node.id))
      .map(item => ({
        id: item.node.id,
        name: item.node.name,
        seriesName: item.node.seriesName ?? null,
        seriesOrder: item.node.seriesOrder ?? null,
      }));
  });

  private setRefreshState(scrollTop: number = 0, sortIndex: number = 0, order: boolean = false, currentPath?: string[]) {
    this.stateService.setState<ManagementRefreshState>(
      environment.management_api + environment.refreshKey + environment.scrollKey,
      {
        scrollPosition: scrollTop,
        sortCriteria: { index: sortIndex, order: order },
        currentPath: currentPath
      } as ManagementRefreshState,
      false
    );
  }

  private getRefreshState(): ManagementRefreshState | undefined {
    return this.stateService.getState<ManagementRefreshState>(
      environment.management_api + environment.refreshKey + environment.scrollKey,
      false
    );
  }

  constructor() {
    const hasValidState = (state: ManagementRefreshState | undefined) =>
      state && Array.isArray(state.currentPath);

    const state = this.getRefreshState();

    if (hasValidState(state)) {
      this.currentPath.set(state!.currentPath!);
    }

    this.setRefreshState(
      state?.scrollPosition ?? 0,
      state?.sortCriteria.index ?? 0,
      state?.sortCriteria.order ?? true,
      state?.currentPath
    );

    effect(() => {
      const path = this.currentPath();
      this.loadDirectory(path);
    });

    merge(
      this.videoUpdateEventService.onEvent(),
      this.videoUpdateEventService.onLocalEvent(),
    ).pipe(takeUntilDestroyed()).subscribe(event => {
      if (this.isAffectedByEvent(event)) {
        this.refreshDirectory();
        this.selectedIds.set(new Set());
      }
    });
  }

  private isAffectedByEvent(event: VideoUpdateEvent): boolean {
    const contents = this.directoryContents().data;
    if (!contents) return false;

    const ids = new Set(event.videoIds);
    if (contents.some(item => ids.has(item.node.id))) return true;

    return [event.directoryPath, event.targetDirectoryPath]
      .some(path => path !== undefined && this.touchesCurrentListing(path, contents));
  }

  /** True when `path` is the directory on screen, or one of the rows in it. */
  private touchesCurrentListing(path: string, contents: BrowseDirectoryDetail): boolean {
    const currentDirPath = this.currentPath().join('/');
    if (path === currentDirPath) return true;

    const prefix = currentDirPath ? currentDirPath + '/' : '';
    return contents
      .filter(item => item.node.isDir)
      .some(item => path === prefix + item.node.name);
  }

  ngOnDestroy(): void {
    this.pathHistoryService.clearAllHistory();
  }

  // ─── Directory Data Loading ────────────────────────────────────────

  private loadDirectory(path: string[], skipCache: boolean = false, recursiveCalculation: boolean = true) {
    this.directorySubscription?.unsubscribe();
    const relativePath =  path.length > 0 ? path.join('/') : undefined;
    this.directorySubscription = this.gqlService.browseDirectoryQuery(relativePath, skipCache, recursiveCalculation)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          if(!result.loading && result.data) {
            if (result.data.some(item => item.node.isLocked)){
              this.migrationTracker.trackTasksInDirectory(path.join('/'));
            }
            const newState = this.getRefreshState();
            if(newState?.sortCriteria){
              this.sortCriteria.set(newState.sortCriteria);
              this.sortItemsBy(newState.sortCriteria, result.data);
              this.directoryContents.set({...this.directoryContents(), loading: result.loading, error: result.error});
              setTimeout(() => {
                if(newState !== undefined){
                  this.scrollTo(newState.scrollPosition);
                }
              }, 200);
            }
            this.setRefreshState(
              newState?.scrollPosition ?? 0,
              newState?.sortCriteria?.index ?? 0,
              newState?.sortCriteria?.order ?? true,
              newState?.currentPath ?? (path.length > 0 ? path : this.currentPath())
            );
          }else{
            this.directoryContents.set(result);
          }
          this.selectedIds.set(new Set());
        },
        error: (err) => {
          this.toastService.emitNewToast('Failed to load directory: ' + err.message, ToastType.Error);
        }
      });
  }

  refreshDirectory() {
    const path = this.currentPath();
    const scrollTop = this.getParentScrollContainer()?.scrollTop ?? 0;
    this.setRefreshState(
      scrollTop,
      this.sortCriteria().index,
      this.sortCriteria().order,
      path
    );
    if (this.isSearching()) {
      // The table is showing results, not a listing — reloading the directory under it
      // would silently swap what the toolbar says is on screen.
      this.loadSearchResults();
      return;
    }
    this.loadDirectory(path, true, false);
  }

  // ─── Search ────────────────────────────────────────────────────────

  runSearch(criteria: DirectorySearchCriteria) {
    this.searchCriteria.set(criteria);
    this.loadSearchResults();
  }

  exitSearch() {
    if (!this.isSearching()) return;
    this.searchCriteria.set(null);
    this.loadDirectory(this.currentPath(), true, false);
  }

  private loadSearchResults() {
    const criteria = this.searchCriteria();
    if (!criteria) return;

    this.directorySubscription?.unsubscribe();
    this.directoryContents.set(this.gqlService.initialSignalData<BrowseDirectoryDetail>([]));
    this.directorySubscription = this.gqlService.searchInDirectoryQuery(
      this.currentPath().join('/'), criteria.name, criteria.author, criteria.tags
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.selectedIds.set(new Set());
          this.directoryContents.set(result);
          if (result.data) {
            this.sortItemsBy(this.sortCriteria(), result.data);
            if (result.data.some(item => item.node.isLocked)) {
              this.migrationTracker.trackTasksInDirectory(this.currentPath().join('/'));
            }
          }
        },
        error: (err) => {
          this.toastService.emitNewToast('Failed to search: ' + err.message, ToastType.Error);
        }
      });
  }

  refreshSelectedDirectory(item: FileBrowseNode) {
    const path = this.currentPath().length > 0? this.currentPath().join('/') + '/' + item.node.name : item.node.name;
    this.gqlService.getDirectoryMetadataQuery(path)
    .pipe(takeUntilDestroyed(this.destroyRef))
    .subscribe({
      next: (result) => {
        if (result.data) {
          this.directoryContents.update(contents => {
            const updatedData = contents.data!.map(entry => {
              if (entry.node.id === item.node.id && entry.node.isDir && result.data) {
                return {
                  ...entry,
                  node: {
                    ...entry.node,
                    size: result.data.totalSize,
                    lastModifyTime: result.data.lastModifiedTime
                  }
                };
              }
              return entry;
            });
            return { ...contents, data: updatedData };
          });
        }
      },
      error: (err) => {
        this.toastService.emitNewToast('Failed to refresh directory metadata: ' + err.message, ToastType.Error);
      }
    });
  }

  // ─── Directory Navigation ──────────────────────────────────────────

  onClickFileBrowseNode(node: FileBrowseNode) {
    if(!node.node.isDir) {
      this.toggleSelection(node.node.id);
      return;
    };
    // Entering a directory leaves the result set behind — the listing effect below takes
    // over from here.
    this.searchCriteria.set(null);
    const newPath = [...this.currentPath(), node.node.name];
    this.setRefreshState(0, this.sortCriteria().index, this.sortCriteria().order, newPath);
    this.currentPath.set(newPath);
    this.pathHistoryService.pushNewPath(this.currentPath());
  }

  navigateToPath(path: string[]) {
    this.searchCriteria.set(null);
    this.setRefreshState(0, this.sortCriteria().index, this.sortCriteria().order, path);
    this.currentPath.set(path);
  }

  // ─── Selection ─────────────────────────────────────────────────────

  toggleSelection(id: string) {
    this.selectedIds.update(ids => {
      const newIds = new Set(ids);
      if (newIds.has(id)) {
        newIds.delete(id);
      } else {
        newIds.add(id);
      }
      return newIds;
    });
  }

  toggleSelectAll() {
    const contents = this.directoryContents().data;
    if (!contents) return;

    const selectableItems = contents.filter(item => !item.node.isDir);
    const allSelected = selectableItems.length > 0
      && selectableItems.every(item => this.selectedIds().has(item.node.id));

    if (allSelected) {
      this.selectedIds.set(new Set());
    } else {
      this.selectedIds.set(new Set(selectableItems.map(item => item.node.id)));
    }
  }

  // ─── Sorting ───────────────────────────────────────────────────────

  toggleSort(columnIndex: number){
    this.sortCriteria.update(criteria => {
      if (criteria.index === columnIndex) {
        criteria.order = !criteria.order;
      } else {
        criteria.index = columnIndex;
        criteria.order = true;
      }
      return criteria;
    });
    this.sortItemsBy(this.sortCriteria(), this.directoryContents().data);
  }

  sortItemsBy(sortCriteria: SortCriterion, contents: FileBrowseNode[] | null) {
    if (!contents) return;
    let sortedContents = [...contents];

    const sortComparator = comparatorBySortOption(sortCriteria);
    sortedContents.sort(sortComparator);
    this.directoryContents.set({ ...this.directoryContents(), data: sortedContents });
  }

  // ─── DOM Utilities ─────────────────────────────────────────────────

  private getParentScrollContainer(): HTMLElement | null {
    return document.getElementById(environment.containerIds.rootMainContainerId);
  }

  scrollTo(position: number) {
    const mainContainer = this.getParentScrollContainer();
    if (mainContainer) {
      mainContainer.scrollTo({ top: position, behavior: 'smooth' });
    }
  }

  updateTableWidth(width: number) {
    this.tableWidth.set(width);
  }
}
