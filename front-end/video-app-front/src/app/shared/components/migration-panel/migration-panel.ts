import { Component, inject, signal, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
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
import {
  BrowseDirectoryDetail,
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
  readonly sourceVideoId = this.data.sourceVideoId;
  readonly sourceVideoName = this.data.sourceVideoName;
  readonly sourceFileSize = this.data.sourceFileSize;
  readonly sourceCurrentDir = this.data.sourceCurrentDir;

  // --- Step Management ---
  currentStep = signal<Step>('select');

  // --- Step 1: Target Path Selection ---
  browsePath = signal<string[]>([]);
  browseContents = signal<ResultState<BrowseDirectoryDetail>>({
    loading: true, error: null, data: null
  });
  selectedTargetDir = signal<string | null>(null);

  // --- Step 2: Preflight Results ---
  preflightResult = signal<MigrationPreflightDetail | null>(null);
  preflightLoading = signal(false);
  conflictStrategy = signal<ConflictStrategy | null>(null);

  constructor() {
    this.browseTargetDirectory([]);
  }

  // ─── Target Directory Browsing ─────────────────────────────────────

  browseTargetDirectory(path: string[]) {
    this.browsePath.set(path);
    const relativePath = path.length > 0 ? path.join('/') : undefined;
    this.gqlService.browseDirectoryQuery(relativePath, true, false)
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

  getDirItems() {
    return this.browseContents().data?.filter(item => item.node.isDir) ?? [];
  }

  // ─── Preflight ─────────────────────────────────────────────────────

  runPreflight() {
    const targetDir = this.selectedTargetDir();
    if (!targetDir) return;

    this.preflightLoading.set(true);
    this.gqlService.migrationPreflightMutation({
      sourceVideoId: this.sourceVideoId,
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

  // ─── Start Migration ───────────────────────────────────────────────

  startMigration() {
    const targetDir = this.selectedTargetDir();
    if (!targetDir) return;

    const input = {
      sourceVideoId: this.sourceVideoId,
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

  // ─── Navigation ────────────────────────────────────────────────────

  goBackToSelect() {
    this.currentStep.set('select');
    this.preflightResult.set(null);
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

  canProceedPreflight(): boolean {
    const result = this.preflightResult();
    if (!result) return false;
    if (!result.valid && !result.conflictExists) return false;
    if (result.conflictExists && !this.conflictStrategy()) return false;
    if (result.conflictExists && this.conflictStrategy() === 'skip') return false;
    return true;
  }
}
