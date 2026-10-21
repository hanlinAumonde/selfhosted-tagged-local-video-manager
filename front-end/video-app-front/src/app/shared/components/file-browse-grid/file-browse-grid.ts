import {
  Component,
  input,
  output,
  computed,
  viewChild,
  ElementRef,
  effect,
  inject,
  DestroyRef,
  untracked,
  ChangeDetectionStrategy
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ResultState, BrowsedVideo, FileBrowseNode } from '../../models/GQL-result.model';
import {
  SortCriterion,
  formatDuration,
  formatFileSize,
  isNodeLocked,
  nodeDirectory
} from '../../models/management.model';
import { FileNodeMenu } from '../file-node-menu/file-node-menu';
import { FileThumbnail } from '../file-thumbnail/file-thumbnail';

/**
 * Thumbnail view of a file browser listing. Shares its inputs, outputs and operations
 * menu with `FileBrowseTable`, so `FileBrowser` can swap one for the other freely.
 */
@Component({
  selector: 'app-file-browse-grid',
  imports: [
    MatIconModule,
    MatCheckboxModule,
    MatMenuModule,
    MatTooltipModule,
    FileNodeMenu,
    FileThumbnail
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  // The host is the flex item in FileBrowser's row; without this it shrinks to the tiles' width.
  host: { class: 'flex-1 min-w-0' },
  templateUrl: './file-browse-grid.html'
})
export class FileBrowseGrid {
  // --- Inputs ---
  directoryContents = input.required<ResultState<FileBrowseNode[]>>();
  sortCriteria = input.required<SortCriterion>();
  selectedIds = input.required<Set<string>>();
  currentPath = input.required<string[]>();

  // --- Outputs ---
  sort = output<number>();
  refresh = output<void>();
  nodeClick = output<FileBrowseNode>();
  selectionToggle = output<string>();
  selectAllToggle = output<void>();
  migrationResult = output<boolean>();
  batchSyncDirectoryResult = output<boolean>();
  refreshDirectoryMeta = output<FileBrowseNode>();
  gridResize = output<number>();

  /** Indexes match the table's sortable columns, which is what `comparatorBySortOption` keys on. */
  readonly sortOptions = [
    { index: 0, label: 'Name' },
    { index: 1, label: 'Size' },
    { index: 2, label: 'Last update' },
  ];

  private gridElement = viewChild<ElementRef<HTMLElement>>('gridElement');
  private resizeObserver: ResizeObserver | null = null;

  isAllSelected = computed(() => {
    const contents = this.directoryContents().data;
    if (!contents || contents.length === 0) return false;
    const selectableItems = contents.filter(item => !item.node.isDir);
    return selectableItems.length > 0 && selectableItems.every(item => this.selectedIds().has(item.node.id));
  });

  hasSelection = computed(() => this.selectedIds().size > 0);

  constructor() {
    // The bottom toolbar takes its width from whichever view is on screen.
    effect(() => {
      const element = this.gridElement()?.nativeElement;
      untracked(() => {
        this.resizeObserver?.disconnect();
        if (element) {
          this.resizeObserver = new ResizeObserver(() => this.gridResize.emit(element.offsetWidth));
          this.resizeObserver.observe(element);
        }
      });
    });

    inject(DestroyRef).onDestroy(() => this.resizeObserver?.disconnect());
  }

  isSelected(id: string): boolean {
    return this.selectedIds().has(id);
  }

  isLocked(node: BrowsedVideo): boolean {
    return isNodeLocked(node);
  }

  nodeDirectory(node: BrowsedVideo): string {
    return nodeDirectory(this.currentPath(), node);
  }

  /** One line per fact; rendered with `white-space: pre-line` by the `file-node-tooltip` class. */
  tooltipFor(node: BrowsedVideo): string {
    const size = node.size > 0 ? formatFileSize(node.size) : '-';
    if (node.isDir) {
      return [`Name: ${node.name}`, `Size: ${size}`].join('\n');
    }
    const tags = node.tags.map(tag => tag.name).join(', ');
    return [
      `Name: ${node.name}`,
      `Author: ${node.author || '-'}`,
      `Size: ${size}`,
      `Duration: ${node.duration ? formatDuration(node.duration) : '-'}`,
      `Tags: ${tags || '-'}`,
    ].join('\n');
  }
}
