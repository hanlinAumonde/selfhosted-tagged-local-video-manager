import {
  Component,
  input,
  output,
  computed,
  viewChild,
  ElementRef,
  effect,
  inject,
  signal,
  DestroyRef,
  afterNextRender,
  untracked,
  ChangeDetectionStrategy
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ResultState, BrowsedVideo, FileBrowseNode } from '../../models/GQL-result.model';
import { SortCriterion, formatFileSize, isNodeLocked, nodeDirectory } from '../../models/management.model';
import { environment } from '../../../../environments/environment';
import { FileNodeMenu } from '../file-node-menu/file-node-menu';

@Component({
  selector: 'app-file-browse-table',
  imports: [
    MatIconModule,
    MatButtonModule,
    MatCheckboxModule,
    MatMenuModule,
    MatTooltipModule,
    FileNodeMenu
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './file-browse-table.html'
})
export class FileBrowseTable {
  // --- Inputs ---
  directoryContents = input.required<ResultState<FileBrowseNode[]>>();
  sortCriteria = input.required<SortCriterion>();
  selectedIds = input.required<Set<string>>();
  currentPath = input.required<string[]>();
  visibleTagsCount = input<number>(environment.visibleTagsCountInManagement);

  // --- Outputs ---
  sort = output<number>();
  refresh = output<void>();
  nodeClick = output<FileBrowseNode>();
  selectionToggle = output<string>();
  selectAllToggle = output<void>();
  migrationResult = output<boolean>();
  batchSyncDirectoryResult = output<boolean>();
  refreshDirectoryMeta = output<FileBrowseNode>();
  tableResize = output<number>();

  tableElement = viewChild<ElementRef<HTMLTableElement>>('tableElement');

  private resizeObserver: ResizeObserver | null = null;
  private destroyRef = inject(DestroyRef);

  // --- Column Resize ---
  private readonly MIN_COL_WIDTH = 80;
  columnWidths = signal<number[]>([]);

  colStyle = computed(() => {
    const widths = this.columnWidths();
    if (widths.length === 0) {
      return ['4', '2', '2', '2', '3'];
    }
    return widths.map(w => `0 0 ${w}px`);
  });

  private resizingColumn = false;
  private resizeColIndex = -1;
  private resizeStartX = 0;
  private resizeStartWidths: number[] = [];
  private lastTableWidth = 0;

  // --- Computed ---
  isAllSelected = computed(() => {
    const contents = this.directoryContents().data;
    if (!contents || contents.length === 0) return false;
    const selectableItems = contents.filter(item => !item.node.isDir);
    return selectableItems.length > 0 && selectableItems.every(item => this.selectedIds().has(item.node.id));
  });

  hasSelection = computed(() => this.selectedIds().size > 0);

  private resizeCallback() {
    const tableEl = this.tableElement();
    if(tableEl){
      const width = tableEl.nativeElement.offsetWidth;
      this.tableResize.emit(width);
    }
  }

  private initColumnWidthsFromDOM() {
    const tableEl = this.tableElement();
    if (!tableEl) return;
    const headerRow = tableEl.nativeElement.querySelector('thead tr');
    if (!headerRow) return;
    const ths = Array.from(headerRow.children) as HTMLElement[];
    // ths: 0=checkbox, 1=type, 2=name, 3=size, 4=lastUpdate, 5=author, 6=tags, 7=operations
    this.columnWidths.set([
      ths[2].offsetWidth,
      ths[3].offsetWidth,
      ths[4].offsetWidth,
      ths[5].offsetWidth,
      ths[6].offsetWidth,
    ]);
    this.lastTableWidth = tableEl.nativeElement.offsetWidth;
  }

  private adjustColumnWidthsOnResize() {
    const tableEl = this.tableElement();
    if (!tableEl || this.resizingColumn) return;
    const widths = this.columnWidths();
    if (widths.length === 0 || this.lastTableWidth === 0) return;

    const newTableWidth = tableEl.nativeElement.offsetWidth;
    const oldResizable = widths.reduce((a, b) => a + b, 0);
    const fixedWidth = this.lastTableWidth - oldResizable;
    const newResizable = newTableWidth - fixedWidth;
    if (oldResizable <= 0 || newResizable <= 0) return;

    const ratio = newResizable / oldResizable;
    this.columnWidths.set(widths.map(w => w * ratio));
    this.lastTableWidth = newTableWidth;
  }

  onResizeStart(event: MouseEvent, colIndex: number) {
    event.preventDefault();
    event.stopPropagation();
    this.resizingColumn = true;
    this.resizeColIndex = colIndex;
    this.resizeStartX = event.clientX;
    this.resizeStartWidths = [...this.columnWidths()];
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', this.onResizeMove);
    document.addEventListener('mouseup', this.onResizeEnd);
  }

  private onResizeMove = (event: MouseEvent) => {
    const diff = event.clientX - this.resizeStartX;
    const widths = [...this.resizeStartWidths];
    const idx = this.resizeColIndex;

    const newLeft = widths[idx] + diff;
    const newRight = widths[idx + 1] - diff;

    if (newLeft >= this.MIN_COL_WIDTH && newRight >= this.MIN_COL_WIDTH) {
      widths[idx] = newLeft;
      widths[idx + 1] = newRight;
      this.columnWidths.set(widths);
    }
  };

  private onResizeEnd = () => {
    this.resizingColumn = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    document.removeEventListener('mousemove', this.onResizeMove);
    document.removeEventListener('mouseup', this.onResizeEnd);
  };

  constructor() {
    effect(() => this.resizeCallback());

    effect(() => {
      const tableEl = this.tableElement()?.nativeElement;
      untracked(() => {
        if (tableEl) {
          this.resizeObserver?.disconnect();
          this.resizeObserver = new ResizeObserver(() => {
            this.resizeCallback();
            this.adjustColumnWidthsOnResize();
          });
          this.resizeObserver.observe(tableEl);
        }
      });
    });

    afterNextRender(() => this.initColumnWidthsFromDOM());

    this.destroyRef.onDestroy(() => {
      this.resizeObserver?.disconnect();
    });
  }

  // --- Template Helpers ---

  isSelected(id: string): boolean {
    return this.selectedIds().has(id);
  }

  nodeDirectory(node: BrowsedVideo): string {
    return nodeDirectory(this.currentPath(), node);
  }

  isLocked(node: BrowsedVideo): boolean {
    return isNodeLocked(node);
  }

  formatSize(bytes: number): string {
    return formatFileSize(bytes);
  }

  formatDate(timestamp: number): string {
    if (!timestamp) return '-';
    return new Date(timestamp * 1000).toLocaleDateString('zh-CN');
  }

  getVisibleTags(video: BrowsedVideo): string[] {
    return video.tags?.slice(0, this.visibleTagsCount()).map(t => t.name) ?? [];
  }

  getRemainingTagsCount(video: BrowsedVideo): number {
    const total = video.tags?.length ?? 0;
    return Math.max(0, total - this.visibleTagsCount());
  }

  getAllRemainingTags(video: BrowsedVideo): string {
    return video.tags?.slice(this.visibleTagsCount()).map(t => t.name).join(',  ') ?? '';
  }
}
