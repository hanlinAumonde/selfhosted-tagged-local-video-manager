import { Component, inject, signal, DestroyRef, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { MigrationTrackerService } from '../../../services/migration-tracker-service/migration-tracker.service';
import { ToastService } from '../../../services/toast-service/toast.service';
import { ToastType } from '../../models/toast.model';
import { MigrationStatusEnum, MigrationTaskQueryInput } from '../../../core/graphql/generated/graphql';
import { MigrationTaskListDetail, MigrationTaskItem, ResultState } from '../../models/GQL-result.model';
import { ACTIVE_MIGRATION_STATUSES, MIGRATION_STATUS_MAP, MigrationTaskFilter } from '../../models/migration.model';
import { Pagination } from '../pagination/pagination';

@Component({
  selector: 'app-migration-task-list',
  imports: [
    DecimalPipe,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatProgressBarModule,
    MatTooltipModule,
    Pagination,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './migration-task-list.html'
})
export class MigrationTaskList implements OnInit {
  private gqlService = inject(GqlService);
  private toastService = inject(ToastService);
  private destroyRef = inject(DestroyRef);
  private migrationTracker = inject(MigrationTrackerService);
  readonly statusMap = MIGRATION_STATUS_MAP;
  readonly statusOptions: { label: string; value: MigrationStatusEnum[] | null }[] = [
    { label: 'All tasks', value: null },
    { label: 'Processing', value: ACTIVE_MIGRATION_STATUSES },
    { label: 'Completed', value: [MigrationStatusEnum.Completed] },
    { label: 'Failed', value: [MigrationStatusEnum.Failed] },
    { label: 'Cancelled', value: [MigrationStatusEnum.Cancelled] },
  ];

  tasks = signal<ResultState<MigrationTaskListDetail>>({
    loading: true,
    error: null,
    data: null
  });

  filter = signal<MigrationTaskFilter>({
    statusFilter: null,
    page: 1,
    pageSize: 20,
  });

  activeFilterIndex = signal<number>(0);
  activeProgress = this.migrationTracker.liveProgress;

  constructor() {
    /*
      The tracker owns the watching now, so the list finds out a task ended the
      same way any other view would, instead of by holding the subscription itself.
    */
    this.migrationTracker.onTaskSettled()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.loadTasks());
  }

  ngOnInit() {
    this.loadTasks();
  }

  loadTasks() {
    const f = this.filter();
    const input: MigrationTaskQueryInput = {
      page: f.page,
      pageSize: f.pageSize,
      statusFilter: f.statusFilter?.map(s => s.toString()) ?? undefined,
    };

    this.gqlService.getMigrationTasksQuery(input)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.tasks.set(result);
          if (result.data) {
            this.migrationTracker.track(result.data.tasks);
          }
        },
        error: (err) => {
          this.toastService.emitNewToast('Failed to load migration tasks: ' + err.message, ToastType.Error);
        }
      });
  }

  setStatusFilter(index: number) {
    this.activeFilterIndex.set(index);
    const option = this.statusOptions[index];
    this.filter.update(f => ({ ...f, statusFilter: option.value, page: 1 }));
    this.loadTasks();
  }

  onPageChange(page: number) {
    this.filter.update(f => ({ ...f, page }));
    this.loadTasks();
  }

  cancelTask(taskId: string) {
    this.gqlService.cancelMigrationTaskMutation({ taskId })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          if (result.data?.success) {
            this.migrationTracker.forget(taskId);
            this.toastService.emitNewToast('Migration task cancelled.', ToastType.Success);
            this.loadTasks();
          }
        }
      });
  }

  retryTask(task: MigrationTaskItem) {
    this.migrationTracker.retry(task);
  }

  getProgress(task: MigrationTaskItem): number {
    const live = this.activeProgress().get(task.id);
    if (live) return live.progressPercentage;
    const size = Number(task.fileSize);
    if (size <= 0) return 0;
    return (Number(task.bytesTransferred) / size) * 100;
  }

  getLiveStatus(task: MigrationTaskItem): MigrationStatusEnum {
    return this.activeProgress().get(task.id)?.status ?? task.status;
  }

  formatSize(bytes: number | string): string {
    const n = typeof bytes === 'string' ? Number(bytes) : bytes;
    if (!n || n === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(n) / Math.log(k));
    return parseFloat((n / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  formatTime(timestamp: number): string {
    if (!timestamp) return '-';
    return new Date(timestamp * 1000).toLocaleString('zh-CN');
  }

  totalPages(): number {
    const data = this.tasks().data;
    if (!data || data.pageSize <= 0) return 0;
    return Math.ceil(data.totalCount / data.pageSize);
  }

  isTerminal(status: MigrationStatusEnum): boolean {
    return MIGRATION_STATUS_MAP[status].isTerminal;
  }

  canCancel(status: MigrationStatusEnum): boolean {
    return status === MigrationStatusEnum.Pending || status === MigrationStatusEnum.Processing;
  }

  canRetry(status: MigrationStatusEnum): boolean {
    return status === MigrationStatusEnum.Failed;
  }
}
