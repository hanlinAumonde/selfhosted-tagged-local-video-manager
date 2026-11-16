import { Injectable, inject, signal } from '@angular/core';
import { Observable, Subject, Subscription, takeWhile } from 'rxjs';
import { GqlService } from '../GQL-service/GQL.service';
import { VideoUpdateEventService } from '../video-update-event-service/video-update-event.service';
import { MigrationStatusEnum, MigrationTaskQueryInput } from '../../core/graphql/generated/graphql';
import {
  MigrationBatchSummaryDetail,
  MigrationProgressDetail,
  MigrationTaskItem,
  ResultState,
} from '../../shared/models/GQL-result.model';
import {
  ACTIVE_MIGRATION_STATUSES,
  isMigrationTerminal,
  parentDirectoryOf,
} from '../../shared/models/migration.model';


@Injectable({ providedIn: 'root' })
export class MigrationTrackerService {

  private gqlService = inject(GqlService);
  private videoUpdateEventService = inject(VideoUpdateEventService);

  private watched = new Map<string, MigrationTaskItem>();
  private subscriptions = new Map<string, Subscription>();

  private progress = signal<ReadonlyMap<string, MigrationProgressDetail>>(new Map());
  private settled$ = new Subject<string>();

  /*
    A batch is watched through one subscription for all its children: a batch can hold
    hundreds of queued files, and a WebSocket per child would be one per file.
  */
  private batchSubscriptions = new Map<string, Subscription>();
  private batchTasks = new Map<string, Map<string, MigrationTaskItem>>();
  private batchCompleted = new Map<string, Set<string>>();
  private summaries = signal<ReadonlyMap<string, MigrationBatchSummaryDetail>>(new Map());

  readonly liveProgress = this.progress.asReadonly();
  /** batchId → the latest counts of each batch being watched. */
  readonly batchSummaries = this.summaries.asReadonly();

  /** Fires with a task id each time one reaches a terminal status. */
  onTaskSettled(): Observable<string> {
    return this.settled$.asObservable();
  }

  track(tasks: MigrationTaskItem[]): void {
    for (const task of tasks) {
      if (isMigrationTerminal(task.status) || this.watched.has(task.id)) continue;
      if (task.batchId) {
        this.trackBatch(task.batchId, [task]);
      } else {
        this.watch(task, this.gqlService.migrationProgressSubscription({ taskId: task.id }));
      }
    }
  }

  /**
   * Watch a batch until none of its children is active. `tasks` are the children this
   * tab knows about; only their directories are refreshed when the batch ends, so pass
   * every child that may move a file the user is looking at.
   *
   * Also works on a batch that has already settled: the subscription opens with its
   * counts and ends straight away, which is how a view gets a batch's summary.
   */
  trackBatch(batchId: string, tasks: MigrationTaskItem[] = []): void {
    const known = this.batchTasks.get(batchId) ?? new Map<string, MigrationTaskItem>();
    for (const task of tasks) known.set(task.id, task);
    this.batchTasks.set(batchId, known);
    if (this.batchSubscriptions.has(batchId)) return;

    this.batchCompleted.set(batchId, new Set());
    const release = () => {
      this.batchSubscriptions.delete(batchId);
      this.batchTasks.delete(batchId);
      this.batchCompleted.delete(batchId);
    };

    const subscription = this.gqlService.migrationBatchProgressSubscription({ batchId })
      .subscribe({
        next: (result) => {
          const event = result.data;
          if (!event) return;

          const frame = event.task;
          if (frame) {
            this.progress.update(current => new Map(current).set(frame.taskId, frame));
            if (isMigrationTerminal(frame.status)) {
              if (frame.status === MigrationStatusEnum.Completed) {
                this.batchCompleted.get(batchId)?.add(frame.taskId);
              }
              this.settled$.next(frame.taskId);
            }
          }

          if (event.summary) {
            const summary = event.summary;
            this.summaries.update(current => new Map(current).set(batchId, summary));
            if (summary.active === 0) this.settleBatch(batchId);
          }
        },
        error: release,
        complete: release,
      });
    if (!subscription.closed) {
      this.batchSubscriptions.set(batchId, subscription);
    }
  }

  /**
   * Watch the running tasks whose source or target file sits directly in
   * `directoryPath` (DB-format, '/'-joined — the same shape the file browser holds).
   *
   * Callers gate this on having actually seen a locked entry, so the task list
   * query only runs when something on screen is mid-migration.
   */
  trackTasksInDirectory(directoryPath: string): void {
    const input: MigrationTaskQueryInput = {
      page: 1,
      pageSize: 100,
      statusFilter: ACTIVE_MIGRATION_STATUSES.map(status => status.toString()),
    };

    this.gqlService.getMigrationTasksQuery(input).subscribe({
      next: (result) => {
        const tasks: MigrationTaskItem[] = result.data?.tasks ?? [];
        this.track(tasks.filter(task =>
          parentDirectoryOf(task.sourcePath) === directoryPath ||
          parentDirectoryOf(task.targetPath) === directoryPath
        ));
      },
    });
  }

  /**
   * Retry a failed task and watch the run it starts. Unlike track(), this is an
   * action: the subscription is what tells the backend to re-queue the task.
   */
  retry(task: MigrationTaskItem): void {
    // Guards a double-click: the button stays enabled until the first frame lands,
    // and a second retry subscription would re-queue a task already on its way.
    if (this.watched.has(task.id)) return;
    this.watch(task, this.gqlService.migrationRetrySubscription({ taskId: task.id }));
  }

  /**
   * Stop watching a task whose outcome is already known, e.g. one just cancelled from
   * the UI. Its last live frame is dropped too: views prefer live frames over the task
   * list, so a stale one would keep showing the task as queued.
   */
  forget(taskId: string): void {
    this.subscriptions.get(taskId)?.unsubscribe();
    this.subscriptions.delete(taskId);
    this.watched.delete(taskId);
    this.progress.update(current => {
      if (!current.has(taskId)) return current;
      const next = new Map(current);
      next.delete(taskId);
      return next;
    });
  }

  private watch(task: MigrationTaskItem, frames: Observable<ResultState<MigrationProgressDetail | null>>): void {
    this.watched.set(task.id, task);

    const subscription = frames
      .pipe(takeWhile(result => {
        const status = result.data?.status;
        return status !== undefined && !isMigrationTerminal(status);
      }, true))
      .subscribe({
        next: (result) => {
          const frame = result.data;
          if (!frame) return;

          this.progress.update(current => new Map(current).set(task.id, frame));
          if (isMigrationTerminal(frame.status)) {
            this.settle(task, frame.status);
          }
        },
        error: () => {
          this.watched.delete(task.id);
          this.subscriptions.delete(task.id);
        },
      });
    if (!subscription.closed) {
      this.subscriptions.set(task.id, subscription);
    }
  }

  /*
    The backend refreshes a batch's directory metadata once, after its last child, so
    views are refreshed then too, once per directory pair instead of once per file.
  */
  private settleBatch(batchId: string): void {
    const known = this.batchTasks.get(batchId);
    const completed = this.batchCompleted.get(batchId);
    if (!known || !completed?.size) return;

    const pairs = new Map<string, [string, string]>();
    for (const taskId of completed) {
      const task = known.get(taskId);
      if (!task) continue;
      const pair: [string, string] = [parentDirectoryOf(task.sourcePath), parentDirectoryOf(task.targetPath)];
      pairs.set(pair.join('\n'), pair);
    }
    for (const [sourceDir, targetDir] of pairs.values()) {
      this.videoUpdateEventService.emitMigrated(sourceDir, targetDir);
    }
  }

  private settle(task: MigrationTaskItem, status: MigrationStatusEnum): void {
    this.watched.delete(task.id);
    this.subscriptions.delete(task.id);
    this.settled$.next(task.id);

    // Cancelled and Failed leave the file where it was; only a completed run moved it.
    if (status !== MigrationStatusEnum.Completed) return;

    this.videoUpdateEventService.emitMigrated(
      parentDirectoryOf(task.sourcePath),
      parentDirectoryOf(task.targetPath),
    );
  }
}
