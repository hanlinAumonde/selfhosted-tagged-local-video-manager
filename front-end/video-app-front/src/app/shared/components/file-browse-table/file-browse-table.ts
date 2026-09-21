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
import { RouterLink } from '@angular/router';
import { ResultState, BrowsedVideo, FileBrowseNode } from '../../models/GQL-result.model';
import { SortCriterion } from '../../models/management.model';
import { environment } from '../../../../environments/environment';
import { ToastService } from '../../../services/toast-service/toast.service';
import { ToastType } from '../../models/toast.model';
import { MatDialog } from '@angular/material/dialog';
import { BatchOperationPanel } from '../batch-operation-panel/batch-operation-panel';
import { DeleteCheckPanel } from '../delete-check-panel/delete-check-panel';
import {
  DeleteCheckPanelData,
  DeleteType,
  MigrationPanelData,
  VideoEditPanelData,
  VideoEditPanelMode
} from '../../models/panels.model';
import { VideoEditPanel } from '../video-edit-panel/video-edit-panel';
import { MigrationPanel } from '../migration-panel/migration-panel';

@Component({
  selector: 'app-file-browse-table',
  imports: [
    MatIconModule,
    MatButtonModule,
    MatCheckboxModule,
    MatMenuModule,
    MatTooltipModule,
    RouterLink
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
  editVideoResult = output<boolean>();
  deleteVideoResult = output<boolean>();
  migrationResult = output<boolean>();
  batchSyncDirectoryResult = output<boolean>();
  refreshDirectoryMeta = output<FileBrowseNode>();
  tableResize = output<number>();

  tableElement = viewChild<ElementRef<HTMLTableElement>>('tableElement');

  private toastService = inject(ToastService);
  private dialog = inject(MatDialog);
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

  openEditPanel(video: BrowsedVideo) {
    this.dialog.open(VideoEditPanel, {
      width: '500px',
      data: {
        mode: 'full' as VideoEditPanelMode,
        video: video
      } as VideoEditPanelData
    });
  }

  deleteVideo(video: BrowsedVideo) {
    this.dialog.open(DeleteCheckPanel, {
      width: '400px',
      data: {
        deleteType: DeleteType.Single,
        videoIds: new Set<string>([video.id])
       } as DeleteCheckPanelData
    });
  }

  deleteVideosInDirectory(dirPath: string) {
    this.dialog.open(DeleteCheckPanel, {
      width: '400px',
      data: {
        deleteType: DeleteType.Directory,
        directoryPath: this.currentPath().join('/') + '/' + dirPath
       } as DeleteCheckPanelData
    });
  }

  openMigrationPanel(video: BrowsedVideo) {
    const data: MigrationPanelData = {
      sourceVideoId: video.id,
      sourceVideoName: video.name,
      sourceFileSize: video.size,
      sourceCurrentDir: this.nodeDirectory(video) || '/',
    };

    const dialogRef = this.dialog.open(MigrationPanel, {
      width: '560px',
      data,
    });

    dialogRef.afterClosed().subscribe(result => {
      this.migrationResult.emit(!!result);
    });
  }

  openBatchOperationPanel(dirName:string) {
    if(!dirName) return;
    
    const selectedDirectoryPath = this.currentPath().length > 0 ?
      this.currentPath().join('/') + '/' + dirName : dirName;

    const data = { mode: 'directory', selectedDirectoryPath: selectedDirectoryPath };
    
    this.toastService.clearAllToasts();

    const dialogRef = this.dialog.open(BatchOperationPanel, {
      width: '500px',
      data: data,
      disableClose: true,
    });

    dialogRef.afterClosed().subscribe(result => {
      this.batchSyncDirectoryResult.emit(result? true : false);
    });
  }

  // --- Template Helpers ---

  isSelected(id: string): boolean {
    return this.selectedIds().has(id);
  }

  /**
   * The directory this row actually sits in, in DB path format.
   *
   * For a listing that is the directory on screen. A search result may have come from any
   * depth below it, and carries that offset in `relativePath` — a row's own location is
   * the only thing an operation on it may be told about.
   */
  nodeDirectory(node: BrowsedVideo): string {
    return [this.currentPath().join('/'), node.relativePath]
      .filter(part => !!part)
      .join('/');
  }

  /**
   * Whether a migration task currently holds this file. Directories are never locked —
   * a migration targets a single file.
   */
  isLocked(node: BrowsedVideo): boolean {
    return !node.isDir && node.isLocked;
  }

  /**
   * Row click either enters a directory or toggles selection. Locked files do neither:
   * every operation reachable from a selection would be rejected by the backend anyway.
   */
  onRowClick(item: FileBrowseNode) {
    if (this.isLocked(item.node)) {
      this.toastService.emitNewToast(
        `"${item.node.name}" is being migrated and cannot be modified.`,
        ToastType.Warning
      );
      return;
    }
    this.nodeClick.emit(item);
  }

  formatSize(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
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

  videoPage(video: BrowsedVideo) {
    return [environment.videopage_api, video.id];
  }
}
