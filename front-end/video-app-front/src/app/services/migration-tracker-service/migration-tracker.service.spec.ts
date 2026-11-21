import { TestBed } from '@angular/core/testing';
import { ApolloTestingController, ApolloTestingModule, TestOperation } from 'apollo-angular/testing';
import { DocumentNode } from 'graphql';
import { MockInstance } from 'vitest';

import { MigrationTrackerService } from './migration-tracker.service';
import { VideoUpdateEventService } from '../video-update-event-service/video-update-event.service';
import {
  GetMigrationTasksDocument,
  MigrationBatchProgressDocument,
  MigrationProgressDocument,
  MigrationRetryDocument,
  MigrationStatusEnum,
} from '../../core/graphql/generated/graphql';
import { MigrationBatchSummaryDetail, MigrationProgressDetail } from '../../shared/models/GQL-result.model';
import { ACTIVE_MIGRATION_STATUSES } from '../../shared/models/migration.model';
import { aBatchSummary, aMigrationTask, aProgressFrame } from '../../../testing/migration-fixtures';
import { apolloAsInTheApp } from '../../../testing/apollo-testing';

const { Processing, Completed, Failed, Cancelled, Pending } = MigrationStatusEnum;

/** Apollo hands results to subscribers asynchronously. */
const tick = () => new Promise<void>(resolve => setTimeout(resolve));

describe('MigrationTrackerService', () => {
  let tracker: MigrationTrackerService;
  let apollo: ApolloTestingController;
  let emitMigrated: MockInstance<VideoUpdateEventService['emitMigrated']>;
  let settled: string[];

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [ApolloTestingModule] });
    tracker = TestBed.inject(MigrationTrackerService);
    apollo = apolloAsInTheApp();
    emitMigrated = vi.spyOn(TestBed.inject(VideoUpdateEventService), 'emitMigrated');
    settled = [];
    tracker.onTaskSettled().subscribe(id => settled.push(id));
  });

  /** The open operations of `document`, keyed by the id in their input. */
  async function opened(document: DocumentNode, idField: 'taskId' | 'batchId' = 'taskId') {
    await tick();
    return new Map<string, TestOperation>(
      apollo.match(document).map(op => [op.operation.variables['input'][idField], op]),
    );
  }

  async function pushTaskFrame(op: TestOperation, frame: MigrationProgressDetail, field: string) {
    op.flushData({ [field]: frame });
    await tick();
  }

  const pushProgress = (op: TestOperation, frame: MigrationProgressDetail) =>
    pushTaskFrame(op, frame, 'migrationProgressSubscription');

  async function pushBatch(
    op: TestOperation,
    event: { task?: MigrationProgressDetail; summary?: MigrationBatchSummaryDetail },
  ) {
    op.flushData({
      migrationBatchProgress: {
        __typename: 'MigrationBatchProgress',
        task: event.task ?? null,
        summary: event.summary ?? null,
      },
    });
    await tick();
  }

  describe('track', () => {
    it('opens one progress subscription per active task, however often it is called', async () => {
      /*
        Given two active migration tasks that are not part of a batch
        When track() is called with both tasks, and then again with the same tasks
        Then exactly one migrationProgress subscription is opened for each task
      */
      const tasks = [aMigrationTask({ status: Pending }), aMigrationTask({ status: Processing })];

      tracker.track(tasks);
      tracker.track(tasks);

      await tick();
      const ops = apollo.match(MigrationProgressDocument);
      expect(ops.map(op => op.operation.variables['input'].taskId)).toEqual(tasks.map(t => t.id));
    });

    it('ignores tasks that have already reached a terminal status', async () => {
      /*
        Given a completed, a failed and a cancelled task
        When track() is called with them
        Then no subscription is opened
      */
      tracker.track([
        aMigrationTask({ status: Completed }),
        aMigrationTask({ status: Failed }),
        aMigrationTask({ status: Cancelled }),
      ]);

      await tick();
      apollo.verify();
    });

    it('hands batch children to a single batch subscription', async () => {
      /*
        Given two queued children of batch "b1" and one child of batch "b2"
        When track() is called with all three
        Then one migrationBatchProgress subscription is opened for "b1" and one for "b2"
        And no per-task migrationProgress subscription is opened
      */
      tracker.track([
        aMigrationTask({ batchId: 'b1', status: Pending }),
        aMigrationTask({ batchId: 'b1', status: Processing }),
        aMigrationTask({ batchId: 'b2', status: Pending }),
      ]);

      await tick();
      const batchOps = apollo.match(MigrationBatchProgressDocument);
      expect(batchOps.map(op => op.operation.variables['input'].batchId)).toEqual(['b1', 'b2']);
      apollo.verify();
    });

    it('publishes each progress frame in liveProgress', async () => {
      /*
        Given a tracked task
        When the backend pushes a PROCESSING frame and then a later PROCESSING frame
        Then liveProgress holds the latest frame under the task id
      */
      const task = aMigrationTask({ status: Processing });
      tracker.track([task]);
      const op = (await opened(MigrationProgressDocument)).get(task.id)!;

      await pushProgress(op, aProgressFrame(task.id, Processing, 200));
      const latest = aProgressFrame(task.id, Processing, 600);
      await pushProgress(op, latest);

      expect(tracker.liveProgress().get(task.id)).toEqual(latest);
    });

    it('announces a completed task and refreshes its source and target directories', async () => {
      /*
        Given a tracked task moving "local/a/x.mp4" to "local/b/x.mp4"
        When the backend pushes a COMPLETED frame
        Then onTaskSettled() emits the task id
        And a Migrated event is emitted for source directory "local/a" and target directory "local/b"
        And the subscription is closed
      */
      const task = aMigrationTask({ sourcePath: 'local/a/x.mp4', targetPath: 'local/b/x.mp4' });
      tracker.track([task]);
      const op = (await opened(MigrationProgressDocument)).get(task.id)!;

      await pushProgress(op, aProgressFrame(task.id, Completed, 1000));

      expect(settled).toEqual([task.id]);
      expect(emitMigrated).toHaveBeenCalledExactlyOnceWith('local/a', 'local/b');
      // A closed subscription no longer delivers frames.
      await pushProgress(op, aProgressFrame(task.id, Processing, 5));
      expect(tracker.liveProgress().get(task.id)?.status).toBe(Completed);
    });

    it('announces failed and cancelled tasks without refreshing any directory', async () => {
      /*
        Given two tracked tasks
        When the backend pushes a FAILED frame for one and a CANCELLED frame for the other
        Then onTaskSettled() emits both task ids
        And no Migrated event is emitted
      */
      const failing = aMigrationTask({ status: Processing });
      const cancelled = aMigrationTask({ status: Pending });
      tracker.track([failing, cancelled]);
      const ops = await opened(MigrationProgressDocument);

      await pushProgress(ops.get(failing.id)!, aProgressFrame(failing.id, Failed, 300));
      await pushProgress(ops.get(cancelled.id)!, aProgressFrame(cancelled.id, Cancelled));

      expect(settled).toEqual([failing.id, cancelled.id]);
      expect(emitMigrated).not.toHaveBeenCalled();
    });

    it('can track a task again once its subscription has ended', async () => {
      /*
        Given a tracked task whose subscription ended in an error
        When track() is called with the same task again
        Then a new migrationProgress subscription is opened
      */
      const task = aMigrationTask({ status: Processing });
      tracker.track([task]);
      const op = (await opened(MigrationProgressDocument)).get(task.id)!;
      op.networkError(new Error('socket closed'));
      await tick();

      tracker.track([task]);

      expect((await opened(MigrationProgressDocument)).has(task.id)).toBe(true);
    });
  });

  describe('trackBatch', () => {
    it('publishes child frames in liveProgress and announces children that settle', async () => {
      /*
        Given a tracked batch with two children
        When the backend pushes a PROCESSING frame for one child and a FAILED frame for the other
        Then liveProgress holds both frames under their task ids
        And onTaskSettled() emits only the failed child's id
      */
      const running = aMigrationTask({ batchId: 'b1', status: Processing });
      const failing = aMigrationTask({ batchId: 'b1', status: Processing });
      tracker.trackBatch('b1', [running, failing]);
      const op = (await opened(MigrationBatchProgressDocument, 'batchId')).get('b1')!;

      const runningFrame = aProgressFrame(running.id, Processing, 400);
      const failedFrame = aProgressFrame(failing.id, Failed, 100);
      await pushBatch(op, { task: runningFrame });
      await pushBatch(op, { task: failedFrame });

      expect(tracker.liveProgress().get(running.id)).toEqual(runningFrame);
      expect(tracker.liveProgress().get(failing.id)).toEqual(failedFrame);
      expect(settled).toEqual([failing.id]);
    });

    it('publishes each summary in batchSummaries', async () => {
      /*
        Given a tracked batch
        When the backend pushes a summary with 3 active and then one with 2 active
        Then batchSummaries holds the later summary under the batch id
      */
      tracker.trackBatch('b1');
      const op = (await opened(MigrationBatchProgressDocument, 'batchId')).get('b1')!;

      await pushBatch(op, { summary: aBatchSummary('b1', { total: 3, active: 3 }) });
      const later = aBatchSummary('b1', { total: 3, active: 2, completed: 1 });
      await pushBatch(op, { summary: later });

      expect(tracker.batchSummaries().get('b1')).toEqual(later);
    });

    it('refreshes each directory pair once when the batch settles', async () => {
      /*
        Given a tracked batch with four children:
          two moving from "local/a" to "local/b",
          one moving from "local/c" to "local/b",
          and one moving from "local/d" to "local/b"
        When the backend pushes COMPLETED frames for the first three children,
          a FAILED frame for the fourth,
          and finally a summary with 0 active
        Then a Migrated event is emitted once for ("local/a", "local/b")
        And once for ("local/c", "local/b")
        And none for ("local/d", "local/b")
      */
      const children = [
        aMigrationTask({ batchId: 'b1', status: Processing, sourcePath: 'local/a/1.mp4', targetPath: 'local/b/1.mp4' }),
        aMigrationTask({ batchId: 'b1', status: Pending, sourcePath: 'local/a/2.mp4', targetPath: 'local/b/2.mp4' }),
        aMigrationTask({ batchId: 'b1', status: Pending, sourcePath: 'local/c/3.mp4', targetPath: 'local/b/3.mp4' }),
        aMigrationTask({ batchId: 'b1', status: Processing, sourcePath: 'local/d/4.mp4', targetPath: 'local/b/4.mp4' }),
      ];
      tracker.trackBatch('b1', children);
      const op = (await opened(MigrationBatchProgressDocument, 'batchId')).get('b1')!;

      for (const child of children.slice(0, 3)) {
        await pushBatch(op, { task: aProgressFrame(child.id, Completed, 1000) });
      }
      await pushBatch(op, { task: aProgressFrame(children[3].id, Failed, 10) });
      expect(emitMigrated).not.toHaveBeenCalled();

      await pushBatch(op, { summary: aBatchSummary('b1', { total: 4, completed: 3, failed: 1 }) });

      expect(emitMigrated.mock.calls).toEqual([
        ['local/a', 'local/b'],
        ['local/c', 'local/b'],
      ]);
    });

    it('refreshes nothing for a batch that had already settled before it was watched', async () => {
      /*
        Given a batch whose children all finished before this tab started watching it
        When trackBatch() is called and the backend pushes only a summary with 0 active
        Then batchSummaries holds that summary
        And no Migrated event is emitted
      */
      const finished = [
        aMigrationTask({ batchId: 'b1', status: Completed }),
        aMigrationTask({ batchId: 'b1', status: Failed }),
      ];
      tracker.trackBatch('b1', finished);
      const op = (await opened(MigrationBatchProgressDocument, 'batchId')).get('b1')!;

      const summary = aBatchSummary('b1', { total: 2, completed: 1, failed: 1 });
      await pushBatch(op, { summary });

      expect(tracker.batchSummaries().get('b1')).toEqual(summary);
      expect(emitMigrated).not.toHaveBeenCalled();
    });

    it('keeps one subscription per batch but remembers children passed in later calls', async () => {
      /*
        Given trackBatch() was called for batch "b1" with child t1 moving from "local/a"
        When trackBatch() is called again for "b1" with child t2 moving from "local/c"
        And the backend pushes COMPLETED frames for t1 and t2 and then a summary with 0 active
        Then only one migrationBatchProgress subscription was opened
        And Migrated events are emitted for both "local/a" and "local/c"
      */
      const t1 = aMigrationTask({ batchId: 'b1', status: Processing, sourcePath: 'local/a/1.mp4', targetPath: 'local/b/1.mp4' });
      const t2 = aMigrationTask({ batchId: 'b1', status: Pending, sourcePath: 'local/c/2.mp4', targetPath: 'local/b/2.mp4' });
      tracker.trackBatch('b1', [t1]);
      tracker.trackBatch('b1', [t2]);

      await tick();
      const ops = apollo.match(MigrationBatchProgressDocument);
      expect(ops).toHaveLength(1);

      await pushBatch(ops[0], { task: aProgressFrame(t1.id, Completed, 1000) });
      await pushBatch(ops[0], { task: aProgressFrame(t2.id, Completed, 1000) });
      await pushBatch(ops[0], { summary: aBatchSummary('b1', { total: 2, completed: 2 }) });

      expect(emitMigrated.mock.calls).toEqual([
        ['local/a', 'local/b'],
        ['local/c', 'local/b'],
      ]);
    });

    it('opens a new subscription for a batch whose previous one has ended', async () => {
      /*
        Given a batch whose subscription has completed
        When trackBatch() is called for the same batch again
        Then a new migrationBatchProgress subscription is opened
      */
      tracker.trackBatch('b1');
      const first = (await opened(MigrationBatchProgressDocument, 'batchId')).get('b1')!;
      await pushBatch(first, { summary: aBatchSummary('b1', { total: 1, completed: 1 }) });
      first.complete();
      await tick();

      tracker.trackBatch('b1');

      expect((await opened(MigrationBatchProgressDocument, 'batchId')).has('b1')).toBe(true);
    });
  });

  describe('trackTasksInDirectory', () => {
    it('tracks only active tasks whose source or target sits directly in the directory', async () => {
      /*
        Given the backend lists four active tasks:
          one with source in "local/a",
          one with target in "local/a",
          one with source in a subdirectory "local/a/sub",
          and one with neither source nor target in "local/a"
        When trackTasksInDirectory("local/a") is called
        Then the task list is queried for active statuses only
        And progress subscriptions are opened for the first two tasks only
      */
      const leaving = aMigrationTask({ status: Processing, sourcePath: 'local/a/1.mp4', targetPath: 'local/b/1.mp4' });
      const arriving = aMigrationTask({ status: Pending, sourcePath: 'local/c/2.mp4', targetPath: 'local/a/2.mp4' });
      const nested = aMigrationTask({ status: Pending, sourcePath: 'local/a/sub/3.mp4', targetPath: 'local/b/3.mp4' });
      const elsewhere = aMigrationTask({ status: Processing, sourcePath: 'local/c/4.mp4', targetPath: 'local/d/4.mp4' });

      tracker.trackTasksInDirectory('local/a');

      await tick();
      const query = apollo.expectOne(GetMigrationTasksDocument);
      expect(query.operation.variables['input'].statusFilter).toEqual(ACTIVE_MIGRATION_STATUSES);
      query.flushData({
        getMigrationTasks: {
          __typename: 'MigrationTaskListResult',
          totalCount: 4,
          page: 1,
          pageSize: 100,
          tasks: [leaving, arriving, nested, elsewhere],
        },
      });

      expect([...(await opened(MigrationProgressDocument)).keys()]).toEqual([leaving.id, arriving.id]);
    });
  });

  describe('retry', () => {
    it('opens a single retry subscription even when clicked twice', async () => {
      /*
        Given a failed task
        When retry() is called twice for it
        Then exactly one migrationRetry subscription is opened
      */
      const task = aMigrationTask({ status: Failed });

      tracker.retry(task);
      tracker.retry(task);

      await tick();
      expect(apollo.match(MigrationRetryDocument)).toHaveLength(1);
    });

    it('handles retry frames the same way as tracked tasks', async () => {
      /*
        Given a failed task moving "local/a/x.mp4" to "local/b/x.mp4" that is being retried
        When the backend pushes a PROCESSING frame and then a COMPLETED frame
        Then liveProgress holds the COMPLETED frame
        And onTaskSettled() emits the task id
        And a Migrated event is emitted for "local/a" and "local/b"
      */
      const task = aMigrationTask({ status: Failed, sourcePath: 'local/a/x.mp4', targetPath: 'local/b/x.mp4' });
      tracker.retry(task);
      const op = (await opened(MigrationRetryDocument)).get(task.id)!;

      await pushTaskFrame(op, aProgressFrame(task.id, Processing, 500), 'migrationRetrySubscription');
      const done = aProgressFrame(task.id, Completed, 1000);
      await pushTaskFrame(op, done, 'migrationRetrySubscription');

      expect(tracker.liveProgress().get(task.id)).toEqual(done);
      expect(settled).toEqual([task.id]);
      expect(emitMigrated).toHaveBeenCalledExactlyOnceWith('local/a', 'local/b');
    });
  });

  describe('forget', () => {
    it('stops watching a task and drops its last live frame', async () => {
      /*
        Given a tracked task with a PROCESSING frame in liveProgress
        When forget() is called for it
        Then its subscription is closed
        And liveProgress no longer holds a frame for it
        And track() opens a new subscription for it afterwards
      */
      const task = aMigrationTask({ status: Processing });
      tracker.track([task]);
      const op = (await opened(MigrationProgressDocument)).get(task.id)!;
      await pushProgress(op, aProgressFrame(task.id, Processing, 300));

      tracker.forget(task.id);

      expect(tracker.liveProgress().has(task.id)).toBe(false);
      await pushProgress(op, aProgressFrame(task.id, Processing, 600));
      expect(tracker.liveProgress().has(task.id)).toBe(false);

      tracker.track([task]);
      expect((await opened(MigrationProgressDocument)).has(task.id)).toBe(true);
    });
  });
});
