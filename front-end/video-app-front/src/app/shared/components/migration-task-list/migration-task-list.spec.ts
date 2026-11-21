import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { ApolloTestingController, ApolloTestingModule, TestOperation } from 'apollo-angular/testing';
import { MockInstance } from 'vitest';

import { MigrationTaskList } from './migration-task-list';
import { ToastType } from '../../models/toast.model';
import { MigrationTaskItem } from '../../models/GQL-result.model';
import { ACTIVE_MIGRATION_STATUSES } from '../../models/migration.model';
import { ToastService } from '../../../services/toast-service/toast.service';
import { MigrationTrackerService } from '../../../services/migration-tracker-service/migration-tracker.service';
import {
  CancelMigrationBatchDocument,
  CancelMigrationTaskDocument,
  GetMigrationTasksDocument,
  MigrationBatchProgressDocument,
  MigrationProgressDocument,
  MigrationRetryDocument,
  MigrationStatusEnum,
  RetryMigrationBatchDocument,
} from '../../../core/graphql/generated/graphql';
import { aBatchSummary, aMigrationTask, aProgressFrame } from '../../../../testing/migration-fixtures';
import { apolloAsInTheApp } from '../../../../testing/apollo-testing';

const { Pending, Processing, Completed, Failed, Cancelled } = MigrationStatusEnum;

/** Apollo hands results to subscribers asynchronously. */
const tick = (ms = 0) => new Promise<void>(resolve => setTimeout(resolve, ms));
/** The list waits this long after a task ends before reloading, to catch a burst of endings. */
const RELOAD_DEBOUNCE = 300;

const task = (name: string, overrides: Partial<MigrationTaskItem> = {}) =>
  aMigrationTask({ id: name, sourcePath: `local/src/${name}.mp4`, targetPath: `local/dst/${name}.mp4`, ...overrides });

describe('MigrationTaskList', () => {
  let fixture: ComponentFixture<MigrationTaskList>;
  let loader: HarnessLoader;
  let apollo: ApolloTestingController;
  let toast: MockInstance<ToastService['emitNewToast']>;
  let forget: MockInstance<MigrationTrackerService['forget']>;

  async function openList() {
    TestBed.configureTestingModule({ imports: [MigrationTaskList, ApolloTestingModule] });
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
    forget = vi.spyOn(TestBed.inject(MigrationTrackerService), 'forget');
    fixture = TestBed.createComponent(MigrationTaskList);
    loader = TestbedHarnessEnvironment.loader(fixture);
    await settle();
  }

  async function settle() {
    await tick();
    await fixture.whenStable();
  }

  // ─── Page reading and interaction ──────────────────────────────────

  const element = () => fixture.nativeElement as HTMLElement;
  const text = () => element().textContent!.replace(/\s+/g, ' ');
  const card = (fileName: string) =>
    [...element().querySelectorAll<HTMLElement>('div.shadow')].find(c => c.textContent!.includes(fileName))!;
  const cardText = (fileName: string) => card(fileName).textContent!.replace(/\s+/g, ' ');
  const buttonIn = (fileName: string, label: string) =>
    [...card(fileName).querySelectorAll('button')].find(b => b.textContent!.includes(label));

  async function click(label: string) {
    await (await loader.getHarness(MatButtonHarness.with({ text: new RegExp(label) }))).click();
    await settle();
  }

  async function clickIn(fileName: string, label: string) {
    buttonIn(fileName, label)!.click();
    await settle();
  }

  // ─── Backend answers ───────────────────────────────────────────────

  const pendingListings = () => apollo.match(GetMigrationTasksDocument);

  async function answerListing(op: TestOperation, tasks: MigrationTaskItem[], totalCount = tasks.length) {
    const { page, pageSize } = op.operation.variables['input'];
    op.flushData({ getMigrationTasks: { __typename: 'MigrationTaskListResult', totalCount, page, pageSize, tasks } });
    await settle();
  }

  /** Answers the one listing being waited for, and returns what it asked for. */
  async function list(tasks: MigrationTaskItem[], totalCount = tasks.length) {
    const op = apollo.expectOne(GetMigrationTasksDocument);
    await answerListing(op, tasks, totalCount);
    return op.operation.variables['input'];
  }

  const watchedTaskIds = () => apollo.match(MigrationProgressDocument).map(op => op.operation.variables['input'].taskId);

  async function pushProgress(op: TestOperation, frame: ReturnType<typeof aProgressFrame>) {
    op.flushData({ migrationProgressSubscription: frame });
    await settle();
  }

  async function answerCancel(result: { success: boolean; status?: MigrationStatusEnum; errorMessage?: string }) {
    const op = apollo.expectOne(CancelMigrationTaskDocument);
    const id = op.operation.variables['input'].taskId;
    op.flushData({
      cancelMigrationTask: {
        __typename: 'MigrationTaskMutationResult',
        success: result.success,
        errorMessage: result.errorMessage ?? null,
        task: result.status
          ? { __typename: 'MigrationTask', id, sourcePath: '', targetPath: '', fileName: '', status: result.status }
          : null,
      },
    });
    await settle();
  }

  /** Opens the list on batch "batch-abc123" holding `tasks`, and returns its progress stream. */
  async function showBatch(tasks: MigrationTaskItem[], counts: Parameters<typeof aBatchSummary>[1]) {
    await openList();
    await list(tasks);
    await clickIn(tasks[0].fileName, 'Batch #abc123');
    await list(tasks);
    const [batch] = apollo.match(MigrationBatchProgressDocument);
    batch.flushData({
      migrationBatchProgress: { __typename: 'MigrationBatchProgress', task: null, summary: aBatchSummary('batch-abc123', counts) },
    });
    await settle();
    return batch;
  }

  // ─── Scenarios ─────────────────────────────────────────────────────

  describe('listing tasks', () => {
    it('says when the tasks are loading, failed to load or there are none', async () => {
      /*
        Given the list is opened
        Then it says the tasks are loading
        When the request fails
        Then it says the tasks failed to load
        When the user refreshes and no task exists
        Then it says there are no migration tasks
      */
      await openList();
      expect(text()).toContain('Loading tasks...');

      apollo.expectOne(GetMigrationTasksDocument).networkError(new Error('down'));
      await settle();
      expect(text()).toContain('Failed to load migration tasks');

      element().querySelector<HTMLButtonElement>('button[mattooltip="Refresh"]')!.click();
      await settle();
      await list([]);
      expect(text()).toContain('No migration tasks');
    });

    it('loads the first page of every task and watches the unfinished ones', async () => {
      /*
        Given a running task "a.mp4" and a completed task "b.mp4" that was renamed to "b (1).mp4"
        When the list is opened
        Then the first 20 tasks of every status are asked for
        And "a.mp4" shows as processing with its source and target
        And "b.mp4" shows as completed, ending at "b (1).mp4", without a progress bar
        And only "a.mp4" is watched for progress
      */
      await openList();

      const asked = await list([
        task('a', { status: Processing }),
        task('b', { status: Completed, renamedTargetPath: 'local/dst/b (1).mp4' }),
      ]);

      expect(asked).toEqual({ page: 1, pageSize: 20 });
      expect(cardText('a.mp4')).toContain('Processing local/src/a.mp4 → local/dst/a.mp4');
      expect(card('a.mp4').querySelector('mat-progress-bar')).not.toBeNull();
      expect(cardText('b.mp4')).toContain('Completed local/src/b.mp4 → local/dst/b (1).mp4');
      expect(card('b.mp4').querySelector('mat-progress-bar')).toBeNull();
      expect(watchedTaskIds()).toEqual(['a']);
    });

    it('shows the live progress of a running task', async () => {
      /*
        Given running task "a.mp4" of 1000 bytes is listed
        When its progress reaches 600 bytes
        Then it shows "60.0%"
      */
      await openList();
      await list([task('a', { status: Processing })]);
      expect(cardText('a.mp4')).toContain('0.0%');

      await pushProgress(apollo.expectOne(MigrationProgressDocument), aProgressFrame('a', Processing, 600));

      expect(cardText('a.mp4')).toContain('600 B / 1000 B');
      expect(cardText('a.mp4')).toContain('60.0%');
    });

    it('filters by status, starting again from the first page', async () => {
      /*
        Given the list shows page 2 of 3
        When the user picks "Processing"
        Then page 1 of the unfinished statuses is asked for
        When the user picks "Failed"
        Then page 1 of the failed tasks is asked for
      */
      await openList();
      await list([task('a', { status: Completed })], 45);
      element().querySelector<HTMLButtonElement>('button[aria-label="Next page"]')!.click();
      await settle();
      expect((await list([task('b', { status: Completed })], 45)).page).toBe(2);

      await click('^Processing$');
      expect(await list([])).toEqual({ page: 1, pageSize: 20, statusFilter: ACTIVE_MIGRATION_STATUSES });

      await click('^Failed$');
      expect(await list([])).toEqual({ page: 1, pageSize: 20, statusFilter: [Failed] });
    });

    it('ignores a listing for a filter the user has already left', async () => {
      /*
        Given the user picked "Completed" and then "Failed" before either listing arrived
        When the failed tasks arrive and then the completed ones arrive late
        Then the failed tasks are shown
      */
      await openList();
      await list([]);
      await click('^Completed$');
      await click('^Failed$');
      const [completed, failed] = pendingListings();

      await answerListing(failed, [task('broken', { status: Failed })]);
      await answerListing(completed, [task('done', { status: Completed })]);

      expect(text()).toContain('broken.mp4');
      expect(text()).not.toContain('done.mp4');
    });

    it('pages through the tasks', async () => {
      /*
        Given 45 tasks exist and 20 are shown per page
        When the user goes to the next page
        Then page 2 is asked for
      */
      await openList();
      await list([task('a', { status: Completed })], 45);

      element().querySelector<HTMLButtonElement>('button[aria-label="Next page"]')!.click();
      await settle();

      expect((await list([])).page).toBe(2);
    });
  });

  describe('acting on a task', () => {
    it('cancels a queued task at once', async () => {
      /*
        Given queued task "a.mp4" is listed and watched
        When the user cancels it and the backend reports it cancelled
        Then it is no longer watched, a toast says it was cancelled and the list is reloaded
      */
      await openList();
      await list([task('a', { status: Pending })]);

      expect(watchedTaskIds()).toEqual(['a']);

      await clickIn('a.mp4', 'Cancel');
      await answerCancel({ success: true, status: Cancelled });

      expect(forget).toHaveBeenCalledExactlyOnceWith('a');
      expect(toast).toHaveBeenCalledExactlyOnceWith('Migration task cancelled.', ToastType.Success);
      await list([task('a', { status: Cancelled })]);
      expect(cardText('a.mp4')).toContain('Cancelled');
    });

    it('waits for a running task to stop after cancelling it', async () => {
      /*
        Given running task "a.mp4" is listed
        When the user cancels it and the backend reports it still processing
        Then its button says "Cancelling…" and is disabled
        When its progress reports it cancelled
        Then the list is reloaded once the burst of endings is over
      */
      await openList();
      await list([task('a', { status: Processing })]);
      const progress = apollo.expectOne(MigrationProgressDocument);

      await clickIn('a.mp4', 'Cancel');
      await answerCancel({ success: true, status: Processing });
      expect(buttonIn('a.mp4', 'Cancelling…')?.disabled).toBe(true);
      expect(toast).toHaveBeenCalledExactlyOnceWith('Cancelling migration task…', ToastType.Success);
      expect(forget).not.toHaveBeenCalled();

      await pushProgress(progress, aProgressFrame('a', Cancelled));
      pendingListings();
      await tick(RELOAD_DEBOUNCE + 50);
      await list([task('a', { status: Cancelled })]);
      expect(cardText('a.mp4')).toContain('Cancelled');
      expect(buttonIn('a.mp4', 'Cancel')).toBeUndefined();
    });

    it('offers to cancel a task again once it is retried after failing instead', async () => {
      /*
        Given running task "a.mp4" was asked to stop and says "Cancelling…"
        When it fails before the cancel reaches it
        And the user retries it and it is running again
        Then "Cancel" is offered again
      */
      await openList();
      await list([task('a', { status: Processing })]);
      const progress = apollo.expectOne(MigrationProgressDocument);
      await clickIn('a.mp4', 'Cancel');
      await answerCancel({ success: true, status: Processing });

      await pushProgress(progress, aProgressFrame('a', Failed));
      await tick(RELOAD_DEBOUNCE + 50);
      await list([task('a', { status: Failed })]);
      await clickIn('a.mp4', 'Retry');
      apollo.expectOne(MigrationRetryDocument).flushData({ migrationRetrySubscription: aProgressFrame('a', Processing, 100) });
      await settle();

      expect(buttonIn('a.mp4', 'Cancelling…')).toBeUndefined();
      expect(buttonIn('a.mp4', 'Cancel')?.disabled).toBe(false);
    });

    it('tells the user why a task could not be cancelled', async () => {
      /*
        Given running task "a.mp4" is listed
        When the user cancels it and the backend refuses with "the task is already committing"
        Then an error toast says "the task is already committing"
        And its "Cancel" button is still offered
      */
      await openList();
      await list([task('a', { status: Processing })]);

      await clickIn('a.mp4', 'Cancel');
      await answerCancel({ success: false, errorMessage: 'the task is already committing' });

      expect(toast).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('the task is already committing'), ToastType.Error);
      expect(buttonIn('a.mp4', 'Cancel')?.disabled).toBe(false);
    });

    it('retries a failed task', async () => {
      /*
        Given failed task "a.mp4" is listed with its error "disk full"
        Then the error is shown and "Retry" is offered
        When the user retries it
        Then a retry of "a.mp4" is started
      */
      await openList();
      await list([task('a', { status: Failed, errorMessage: 'disk full' })]);
      expect(cardText('a.mp4')).toContain('disk full');

      await clickIn('a.mp4', 'Retry');

      expect(apollo.expectOne(MigrationRetryDocument).operation.variables['input']).toEqual({ taskId: 'a' });
    });
  });

  describe('acting on a batch', () => {
    const inBatch = (name: string, status: MigrationStatusEnum) => task(name, { status, batchId: 'batch-abc123' });

    it('shows one batch with its counts', async () => {
      /*
        Given task "a.mp4" of batch "batch-abc123" is listed on page 2
        When the user clicks its batch badge
        Then page 1 of batch "batch-abc123" is asked for and the batch is watched with its tasks
        When the batch reports 3 files, 1 active, 1 completed and 1 failed
        Then those counts are shown with "Cancel batch" and "Retry failed"
        When the user closes the batch
        Then every task is asked for again
      */
      await openList();
      await list([task('x', { status: Completed })], 45);
      element().querySelector<HTMLButtonElement>('button[aria-label="Next page"]')!.click();
      await settle();
      await list([inBatch('a', Completed)], 45);

      await clickIn('a.mp4', 'Batch #abc123');
      expect(await list([inBatch('a', Completed), inBatch('b', Processing), inBatch('c', Failed)]))
        .toEqual({ page: 1, pageSize: 20, batchId: 'batch-abc123' });

      const [batch] = apollo.match(MigrationBatchProgressDocument);
      expect(batch.operation.variables['input']).toEqual({ batchId: 'batch-abc123' });
      batch.flushData({
        migrationBatchProgress: {
          __typename: 'MigrationBatchProgress',
          task: null,
          summary: aBatchSummary('batch-abc123', { total: 3, active: 1, completed: 1, failed: 1 }),
        },
      });
      await settle();
      expect(text()).toContain('Batch #abc123 3 files · 1 active · 1 completed · 1 failed · 0 cancelled');
      expect(text()).toContain('Cancel batch');
      expect(text()).toContain('Retry failed');

      element().querySelector<HTMLButtonElement>('button[mattooltip="Show all batches"]')!.click();
      await settle();
      expect(await list([])).toEqual({ page: 1, pageSize: 20 });
    });

    it('cancels a batch, marking only its running files as cancelling', async () => {
      /*
        Given batch "batch-abc123" is shown with running file "a.mp4" and queued file "b.mp4"
        When the user cancels the batch
        Then "a.mp4" says "Cancelling…" and "b.mp4" does not
        And a toast says the batch is being cancelled and the batch is reloaded
      */
      const tasks = [inBatch('a', Processing), inBatch('b', Pending)];
      await showBatch(tasks, { total: 2, active: 2 });

      await click('Cancel batch');
      const op = apollo.expectOne(CancelMigrationBatchDocument);
      expect(op.operation.variables['input']).toEqual({ batchId: 'batch-abc123' });
      op.flushData({ cancelMigrationBatch: aBatchSummary('batch-abc123', { total: 2, active: 1, cancelled: 1 }) });
      await settle();

      expect(buttonIn('a.mp4', 'Cancelling…')).toBeDefined();
      expect(buttonIn('b.mp4', 'Cancelling…')).toBeUndefined();
      expect(toast).toHaveBeenCalledExactlyOnceWith('Cancelling the batch…', ToastType.Success);
      expect((await list(tasks)).batchId).toBe('batch-abc123');
    });

    it('retries the failed files of a batch', async () => {
      /*
        Given batch "batch-abc123" is shown with a failed file
        When the user clicks "Retry failed"
        Then a retry of batch "batch-abc123" is requested, a toast says so and the batch is reloaded
      */
      const tasks = [inBatch('a', Failed), inBatch('b', Completed)];
      await showBatch(tasks, { total: 2, completed: 1, failed: 1 });

      await click('Retry failed');
      const op = apollo.expectOne(RetryMigrationBatchDocument);
      expect(op.operation.variables['input']).toEqual({ batchId: 'batch-abc123' });
      op.flushData({ retryMigrationBatch: aBatchSummary('batch-abc123', { total: 2, active: 1, completed: 1 }) });
      await settle();

      expect(toast).toHaveBeenCalledExactlyOnceWith('Retrying the failed files of the batch.', ToastType.Success);
      expect((await list(tasks)).batchId).toBe('batch-abc123');
    });
  });
});
