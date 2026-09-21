import { Component, computed, inject, input, output, signal, viewChild, ElementRef, afterEveryRender, effect, untracked, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from "@angular/material/button";
import { PathHistoryService } from '../../../services/path-history-service/path-history.service';
import { ToastService } from '../../../services/toast-service/toast.service';
import { MatDialog } from '@angular/material/dialog';
import { BatchOperationPanel } from '../batch-operation-panel/batch-operation-panel';
import { MatMenuModule } from "@angular/material/menu";
import { MatTooltipModule } from "@angular/material/tooltip";
import { DeleteCheckPanel } from '../delete-check-panel/delete-check-panel';
import { NewFolderPanel } from '../new-folder-panel/new-folder-panel';
import { SearchPanel } from '../search-panel/search-panel';
import {
  BatchPanelVideoItem,
  DeleteCheckPanelData,
  DeleteType,
  DirectorySearchCriteria,
  NewFolderPanelData,
  SearchPanelData
} from '../../models/panels.model';

@Component({
  selector: 'app-bottom-toolbar',
  imports: [MatIconModule, MatButtonModule, MatMenuModule, MatTooltipModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './bottom-toolbar.html'
})
export class BottomToolbar {
  pathHistoryService = inject(PathHistoryService)
  private toastService = inject(ToastService);
  private dialog = inject(MatDialog);
  private destroyRef = inject(DestroyRef);

  currentPath = input.required<string[]>();
  hasSelection = input.required<boolean>();
  selectedCount = input.required<number>();
  selectedIds = input.required<Set<string>>();
  selectedVideoItems = input<ReadonlyArray<BatchPanelVideoItem>>([]);
  isAtRoot = input.required<boolean>();
  tableWidth = input.required<number>();
  /** True while the table is showing search results rather than a directory listing. */
  isSearching = input<boolean>(false);
  /** What was searched for, one chip per field that was filled in. */
  searchSummary = input<string[]>([]);

  batchOperationResult = output<boolean>();
  createFolderResult = output<boolean>();
  navigateToPath = output<string[]>();
  searchRequested = output<DirectorySearchCriteria>();
  exitSearch = output<void>();

  paths = computed(() => {
    return ["Root", ...this.currentPath()];
  });

  /**
   * Only a real directory can hold a new folder. The first two levels are not places on
   * the storage: the root lists categories, and a category lists configured mount points.
   */
  canCreateFolder = computed(() => this.currentPath().length >= 2);

  /** A search walks the storage, so it needs the same kind of place a new folder does. */
  canSearch = computed(() => this.currentPath().length >= 2);

  private pathContainer = viewChild<ElementRef>('pathContainer');

  visibleStartIndex = signal(0);
  hasOverflow = computed(() => this.visibleStartIndex() > 0);
  hiddenPaths = computed(() => this.paths().slice(0, this.visibleStartIndex()));
  visiblePaths = computed(() => this.paths().slice(this.visibleStartIndex()));

  toolbarVisible = signal<boolean>(true);

  private pendingMeasurement = false;
  private cachedItemWidths: number[] = [];
  private cachedSeparatorWidth = 0;
  private resizeObserver: ResizeObserver | null = null;

  constructor() {
    effect(() => {
      this.paths();
      untracked(() => {
        this.visibleStartIndex.set(0);
        this.pendingMeasurement = true;
      });
    });

    afterEveryRender(() => {
      if (this.pendingMeasurement) {
        this.pendingMeasurement = false;
        this.measureAndCompute();
      }
    });

    effect(() => {
      const container = this.pathContainer()?.nativeElement;
      untracked(() => {
        this.resizeObserver?.disconnect();
        if (container) {
          this.resizeObserver = new ResizeObserver(() => {
            if (this.cachedItemWidths.length > 0) {
              this.computeVisibleStart((container as HTMLElement).clientWidth);
            }
          });
          this.resizeObserver.observe(container);
        }
      });
    });

    this.destroyRef.onDestroy(() => {
      this.resizeObserver?.disconnect();
    });
  }

  private measureAndCompute() {
    const container = this.pathContainer()?.nativeElement as HTMLElement;
    if (!container) return;

    const items = container.querySelectorAll('.path-item');
    const separators = container.querySelectorAll('.path-sep');
    if (items.length === 0) return;

    this.cachedItemWidths = Array.from(items).map(el => (el as HTMLElement).offsetWidth);
    this.cachedSeparatorWidth = separators.length > 0
      ? (separators[0] as HTMLElement).offsetWidth
      : 0;

    this.computeVisibleStart(container.clientWidth);
  }

  private computeVisibleStart(containerWidth: number) {
    if (containerWidth <= 0) return;

    const totalWidth = this.cachedItemWidths.reduce((sum, w) => sum + w, 0)
      + Math.max(0, this.cachedItemWidths.length - 1) * this.cachedSeparatorWidth;

    if (totalWidth <= containerWidth) {
      if (this.visibleStartIndex() !== 0) {
        this.visibleStartIndex.set(0);
      }
      return;
    }

    const btnWidth = 48;
    const availableWidth = containerWidth - btnWidth - this.cachedSeparatorWidth;

    let currentWidth = 0;
    let startIndex = this.cachedItemWidths.length;

    for (let i = this.cachedItemWidths.length - 1; i >= 0; i--) {
      const elementWidth = this.cachedItemWidths[i];
      const sepWidth = (i < this.cachedItemWidths.length - 1) ? this.cachedSeparatorWidth : 0;
      const addedWidth = elementWidth + sepWidth;

      if (currentWidth + addedWidth > availableWidth) break;
      currentWidth += addedWidth;
      startIndex = i;
    }

    if (startIndex >= this.cachedItemWidths.length) {
      startIndex = Math.max(0, this.cachedItemWidths.length - 1);
    }

    if (this.visibleStartIndex() !== startIndex) {
      this.visibleStartIndex.set(startIndex);
    }
  }

  toggleToolbar() {
    this.toolbarVisible.update(v => !v);
  }

  navigateOnClickButton(back: boolean = true){
    this.navigateToPath.emit(
      (back? this.pathHistoryService.popHisotryPath() : this.pathHistoryService.pushForwardPath())
       ?? []
    );
  }

  navigateOnClickPathElement(index: number){
    if(index < 0 || index > this.currentPath().length) return;
    if(index === this.currentPath().length) return;
    const targetPath = this.currentPath().slice(0, index);
    this.pathHistoryService.pushNewPath(targetPath);
    this.navigateToPath.emit(targetPath);
  }

  openNewFolderPanel() {
    if (!this.canCreateFolder()) return;

    this.toastService.clearAllToasts();

    const dialogRef = this.dialog.open(NewFolderPanel, {
      width: '400px',
      data: { parentPath: this.currentPath().join('/') } as NewFolderPanelData,
    });

    dialogRef.afterClosed().subscribe(result => {
      this.createFolderResult.emit(result ? true : false);
    });
  }

  openSearchPanel() {
    if (!this.canSearch()) return;

    this.toastService.clearAllToasts();

    const dialogRef = this.dialog.open(SearchPanel, {
      width: '480px',
      data: { directoryPath: this.currentPath().join('/') } as SearchPanelData,
    });

    dialogRef.afterClosed().subscribe((criteria: DirectorySearchCriteria | undefined) => {
      if (criteria) {
        this.searchRequested.emit(criteria);
      }
    });
  }

  openBatchOperationPanel() {
    if (this.selectedIds().size === 0) return;

    const data = {
      mode: 'videos',
      videos: this.selectedIds(),
      videoItems: this.selectedVideoItems(),
    };

    this.toastService.clearAllToasts();

    const dialogRef = this.dialog.open(BatchOperationPanel, {
      width: '500px',
      data: data,
      disableClose: true,
    });

    dialogRef.afterClosed().subscribe(result => {
      this.batchOperationResult.emit(result? true : false);
    });
  }

  openBatchDeleteCheckPanel() {
    if (this.selectedIds().size === 0) return;
    this.toastService.clearAllToasts();

    this.dialog.open(DeleteCheckPanel, {
      width: '400px',
      data: {
        deleteType: DeleteType.Batch,
        videoCount: this.selectedIds().size,
        videoIds: this.selectedIds(),
        directoryPath: this.isAtRoot() ? "" : this.currentPath().join("/")
      } as DeleteCheckPanelData
    });
  }
}