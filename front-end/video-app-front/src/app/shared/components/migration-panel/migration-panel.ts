import { Component, inject, signal, computed, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription } from 'rxjs';
import { MatDialogRef, MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatRadioModule } from '@angular/material/radio';
import { MatTooltipModule } from '@angular/material/tooltip';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { MigrationTrackerService } from '../../../services/migration-tracker-service/migration-tracker.service';
import { ToastService } from '../../../services/toast-service/toast.service';
import { ToastType } from '../../models/toast.model';
import { MigrationPanelData } from '../../models/panels.model';
import { ConflictStrategy } from '../../models/migration.model';
import { comparatorBySortOption } from '../../models/management.model';
import {
  BrowseDirectoryDetail,
  CreateMigrationBatchDetail,
  MigrationBatchPreflightDetail,
  MigrationBatchPreflightItem,
  MigrationPreflightDetail,
  ResultState,
} from '../../models/GQL-result.model';

type Step = 'select' | 'preflight';

@Component({
  selector: 'app-migration-panel',
  imports: [
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatRadioModule,
    MatTooltipModule,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './migration-panel.html'
})
export class MigrationPanel {
  private data = inject<MigrationPanelData>(MAT_DIALOG_DATA);
  private dialogRef = inject(MatDialogRef<MigrationPanel>);
  private gqlService = inject(GqlService);
  private destroyRef = inject(DestroyRef);
  private toastService = inject(ToastService);
  private migrationTracker = inject(MigrationTrackerService);

  // --- Source Info ---
  readonly videos = this.data.videos;
  readonly isBatch = this.videos.length > 1;
  readonly sourceVideoName = this.isBatch ? `${this.videos.length} videos` : this.videos[0].name;
  readonly sourceFileSize = this.videos.reduce((sum, video) => sum + video.size, 0);
  readonly sourceCurrentDir = this.data.sourceCurrentDir;
  private readonly nameById = new Map(this.videos.map(video => [video.id, video.name]));

  // --- Step Management ---
  currentStep = signal<Step>('select');

  // --- Step 1: Target Path Selection ---
  browsePath = signal<string[]>([]);
  browseContents = signal<ResultState<BrowseDirectoryDetail>>({
    loading: true, error: null, data: null
  });
  selectedTargetDir = signal<string | null>(null);
  dirFilter = signal('');
  sortAscending = signal(true);
  private browseSubscription?: Subscription;

  readonly visibleDirItems = computed(() => {
    const keyword = this.dirFilter().trim().toLowerCase();
    const dirs = this.browseContents().data?.filter(item => item.node.isDir) ?? [];
    return dirs
      .filter(item => !keyword || item.node.name.toLowerCase().includes(keyword))
      .sort(comparatorBySortOption({ index: 0, order: this.sortAscending() }));
  });

  // --- Step 2: Preflight Results ---
  preflightResult = signal<MigrationPreflightDetail | null>(null);
  batchPreflight = signal<MigrationBatchPreflightDetail | null>(null);
  preflightLoading = signal(false);
  conflictStrategy = signal<ConflictStrategy | null>(null);

  /*
    A batch only sends the files that passed. A file failing a check (already migrating,
    or already in the target) would otherwise be created anyway: creation does not
    repeat those checks, which is why the single-file flow blocks on them too.
  */
  readonly batchReady = computed(() =>
    this.batchPreflight()?.items.filter(item => item.result.valid && !item.result.conflictExists) ?? []);
  readonly batchConflicts = computed(() =>
    this.batchPreflight()?.items.filter(item => item.result.valid && item.result.conflictExists) ?? []);
  readonly batchExcluded = computed(() =>
    this.batchPreflight()?.items.filter(item => !item.result.valid) ?? []);

  constructor() {
    this.browseTargetDirectory([]);
  }

  // ─── Target Directory Browsing ─────────────────────────────────────

  browseTargetDirectory(path: string[]) {
    this.browsePath.set(path);
    // The keyword was typed against the previous listing; carrying it over would hide the new one.
    this.dirFilter.set('');
    // A slower listing for a directory the user already left would otherwise land after
    // the one they navigated to and overwrite it.
    this.browseSubscription?.unsubscribe();
    const relativePath = path.length > 0 ? path.join('/') : undefined;
    this.browseSubscription = this.gqlService.browseDirectoryQuery(relativePath, true, false)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.browseContents.set(result);
        }
      });
  }

  navigateInto(dirName: string) {
    const newPath = [...this.browsePath(), dirName];
    this.browseTargetDirectory(newPath);
  }

  navigateToBreadcrumb(index: number) {
    const newPath = this.browsePath().slice(0, index);
    this.browseTargetDirectory(newPath);
  }

  selectCurrentDirectory() {
    const path = this.browsePath();
    if (path.length === 0) return;
    this.selectedTargetDir.set(path.join('/'));
  }

  toggleSort() {
    this.sortAscending.update(asc => !asc);
  }

  // ─── Preflight ─────────────────────────────────────────────────────

  runPreflight() {
    const targetDir = this.selectedTargetDir();
    if (!targetDir) return;

    this.preflightLoading.set(true);
    if (this.isBatch) {
      this.runBatchPreflight(targetDir);
      return;
    }
    this.gqlService.migrationPreflightMutation({
      sourceVideoId: this.videos[0].id,
      targetDirRelativePath: { relativePath: targetDir },
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.preflightLoading.set(false);
          if (result.data) {
            this.preflightResult.set(result.data);
            this.currentStep.set('preflight');
            if (result.data.conflictExists) {
              this.conflictStrategy.set('rename');
            }
          }
        },
        error: () => {
          this.preflightLoading.set(false);
        }
      });
  }

  private runBatchPreflight(targetDir: string) {
    this.gqlService.migrationBatchPreflightMutation({
      sourceVideoIds: this.videos.map(video => video.id),
      targetDirRelativePath: { relativePath: targetDir },
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.preflightLoading.set(false);
          if (result.data) {
            this.batchPreflight.set(result.data);
            this.currentStep.set('preflight');
            if (this.batchConflicts().length > 0) {
              this.conflictStrategy.set('rename');
            }
          }
        },
        error: () => {
          this.preflightLoading.set(false);
        }
      });
  }

  // ─── Start Migration ───────────────────────────────────────────────

  startMigration() {
    const targetDir = this.selectedTargetDir();
    if (!targetDir) return;
    if (this.isBatch) {
      this.startBatchMigration(targetDir);
      return;
    }

    const input = {
      sourceVideoId: this.videos[0].id,
      targetDirRelativePath: { relativePath: targetDir },
      conflictStrategy: this.conflictStrategy() ?? undefined,
    };

    this.gqlService.createMigrationTaskMutation(input)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          if (result.data?.success) {
            if (result.data.task) {
              this.migrationTracker.track([result.data.task]);
            }
            this.toastService.emitNewToast(
              `Migration task created successfully. You can view its progress in the task management panel.`,
              ToastType.Success
            );
            this.dialogRef.close(true);
          } else if (result.data?.errorMessage) {
            this.toastService.emitNewToast(result.data.errorMessage, ToastType.Error);
          }
        }
      });
  }

  private startBatchMigration(targetDir: string) {
    const strategy = this.batchConflicts().length > 0 ? this.conflictStrategy() : null;
    const sent = strategy === 'skip' ? this.batchReady() : [...this.batchReady(), ...this.batchConflicts()];

    this.gqlService.createMigrationBatchMutation({
      sourceVideoIds: sent.map(item => item.sourceVideoId),
      targetDirRelativePath: { relativePath: targetDir },
      conflictStrategy: strategy ?? undefined,
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          if (!result.data) return;
          this.reportBatchCreation(result.data);
          if (result.data.batchId) {
            this.migrationTracker.trackBatch(result.data.batchId, result.data.tasks);
            this.dialogRef.close(true);
          }
        }
      });
  }

  private reportBatchCreation(creation: CreateMigrationBatchDetail) {
    const skipped = creation.skipped
      .map(skip => `${this.nameOf(skip.sourceVideoId)}: ${skip.reason}`)
      .join('; ');

    if (!creation.batchId) {
      this.toastService.emitNewToast(`No migration task was created. ${skipped}`, ToastType.Error);
    } else if (skipped) {
      this.toastService.emitNewToast(
        `${creation.tasks.length} migration tasks created, ${creation.skipped.length} skipped. ${skipped}`,
        ToastType.Warning
      );
    } else {
      this.toastService.emitNewToast(
        `${creation.tasks.length} migration tasks created. You can view their progress in the task management panel.`,
        ToastType.Success
      );
    }
  }

  // ─── Navigation ────────────────────────────────────────────────────

  goBackToSelect() {
    this.currentStep.set('select');
    this.preflightResult.set(null);
    this.batchPreflight.set(null);
    this.conflictStrategy.set(null);
  }

  closeDialog() {
    this.dialogRef.close(false);
  }

  // ─── Helpers ───────────────────────────────────────────────────────

  formatSize(bytes: number | string): string {
    const n = typeof bytes === 'string' ? Number(bytes) : bytes;
    if (!n || n === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(n) / Math.log(k));
    return parseFloat((n / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  nameOf(videoId: string): string {
    return this.nameById.get(videoId) ?? videoId;
  }

  /** Why a file is left out of the batch, for the list of excluded files. */
  exclusionReason(item: MigrationBatchPreflightItem): string {
    if (item.result.sameLocation) return 'already in the target directory';
    if (item.result.alreadyMigrating) return 'already being migrated';
    return item.result.errorMessage ?? 'failed the checks';
  }

  canProceedPreflight(): boolean {
    if (this.isBatch) return this.canProceedBatch();
    const result = this.preflightResult();
    if (!result) return false;
    if (!result.valid && !result.conflictExists) return false;
    if (result.conflictExists && !this.conflictStrategy()) return false;
    if (result.conflictExists && this.conflictStrategy() === 'skip') return false;
    return true;
  }

  private canProceedBatch(): boolean {
    const preflight = this.batchPreflight();
    if (!preflight || preflight.spaceSufficient === false) return false;
    if (this.batchConflicts().length === 0) return this.batchReady().length > 0;
    const strategy = this.conflictStrategy();
    if (!strategy) return false;
    return strategy !== 'skip' || this.batchReady().length > 0;
  }
}
