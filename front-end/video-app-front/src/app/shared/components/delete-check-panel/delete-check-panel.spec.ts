import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatRadioButtonHarness } from '@angular/material/radio/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { ApolloTestingController, ApolloTestingModule, TestOperation } from 'apollo-angular/testing';
import { MockInstance } from 'vitest';

import { DeleteCheckPanel } from './delete-check-panel';
import { DeleteCheckPanelData, DeleteType } from '../../models/panels.model';
import { ToastType } from '../../models/toast.model';
import { ToastService } from '../../../services/toast-service/toast.service';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import {
  BatchDeleteSubscriptionDocument,
  BatchResultType,
  DeleteVideoDocument,
  DirectoryDeletionStrategy,
} from '../../../core/graphql/generated/graphql';
import { apolloAsInTheApp } from '../../../../testing/apollo-testing';

/** Apollo hands results to subscribers asynchronously. */
const tick = () => new Promise<void>(resolve => setTimeout(resolve));

describe('DeleteCheckPanel', () => {
  let fixture: ComponentFixture<DeleteCheckPanel>;
  let loader: HarnessLoader;
  let apollo: ApolloTestingController;
  let close: ReturnType<typeof vi.fn>;
  let toast: MockInstance<ToastService['emitNewToast']>;
  let videosDeleted: MockInstance<VideoUpdateEventService['emitVideosDeleted']>;
  let directoryDeleted: MockInstance<VideoUpdateEventService['emitDirectoryDeleted']>;

  async function openPanel(data: DeleteCheckPanelData) {
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [DeleteCheckPanel, ApolloTestingModule],
      providers: [
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
    const events = TestBed.inject(VideoUpdateEventService);
    videosDeleted = vi.spyOn(events, 'emitVideosDeleted').mockImplementation(() => {});
    directoryDeleted = vi.spyOn(events, 'emitDirectoryDeleted').mockImplementation(() => {});

    fixture = TestBed.createComponent(DeleteCheckPanel);
    loader = TestbedHarnessEnvironment.loader(fixture);
    await settle();
  }

  async function settle() {
    await tick();
    await fixture.whenStable();
  }

  const text = () => (fixture.nativeElement as HTMLElement).textContent!.replace(/\s+/g, ' ');
  const yes = () => loader.getHarness(MatButtonHarness.with({ text: 'Yes' }));

  async function confirm() {
    await (await yes()).click();
    await settle();
  }

  const openSingle = () => openPanel({ deleteType: DeleteType.Single, videoIds: new Set(['v1']) });
  const openBatch = () => openPanel({
    deleteType: DeleteType.Batch,
    videoCount: 2,
    videoIds: new Set(['v1', 'v2']),
    directoryPath: 'local/movies',
  });
  const openDirectory = () => openPanel({ deleteType: DeleteType.Directory, directoryPath: 'local/old' });

  async function answerSingle(op: TestOperation, success: boolean) {
    op.flushData({
      deleteVideo: { __typename: 'VideoMutationResult', success, video: success ? { __typename: 'Video', id: 'v1' } : null },
    });
    await settle();
  }

  const batchFrame = (status: string | null, result: { resultType: BatchResultType; message: string } | null) => ({
    batchDeleteSubscription: {
      __typename: 'BatchOperationStatus',
      status,
      result: result && { __typename: 'VideosBatchOperationResult', ...result },
    },
  });

  async function reportResult(op: TestOperation, resultType: BatchResultType, message = 'done') {
    op.flushData(batchFrame(null, { resultType, message }));
    await settle();
  }

  async function confirmedBatch() {
    await openBatch();
    await confirm();
    return apollo.expectOne(BatchDeleteSubscriptionDocument);
  }

  describe('one video', () => {
    it('deletes the video and announces it', async () => {
      /*
        Given the panel is opened to delete video "v1"
        Then it asks whether to delete this video
        When the user confirms
        Then a deletion of "v1" is sent
        When the backend reports success
        Then "v1" is announced as deleted, a success toast is shown and the panel closes reporting success
      */
      await openSingle();
      expect(text()).toContain('Are you sure you want to delete this video?');

      await confirm();
      const op = apollo.expectOne(DeleteVideoDocument);
      expect(op.operation.variables).toEqual({ videoId: 'v1' });

      await answerSingle(op, true);
      expect(videosDeleted).toHaveBeenCalledExactlyOnceWith(['v1']);
      expect(toast).toHaveBeenCalledExactlyOnceWith('Video deleted successfully.', ToastType.Success);
      expect(close).toHaveBeenCalledExactlyOnceWith(true);
    });

    it('closes reporting failure when the video could not be deleted', async () => {
      /*
        Given the user has confirmed deleting video "v1"
        When the backend reports the deletion did not succeed
        Then an error toast is shown, nothing is announced and the panel closes reporting failure
      */
      await openSingle();
      await confirm();

      await answerSingle(apollo.expectOne(DeleteVideoDocument), false);

      expect(toast).toHaveBeenCalledExactlyOnceWith('Failed to delete video.', ToastType.Error);
      expect(videosDeleted).not.toHaveBeenCalled();
      expect(close).toHaveBeenCalledExactlyOnceWith(false);
    });

    it('lets a deletion finish after the panel is gone, without sending it again', async () => {
      /*
        Given the user has confirmed deleting video "v1"
        When the panel is destroyed before the backend answers
        Then no second deletion is sent
        When the backend then reports success
        Then "v1" is still announced as deleted
      */
      await openSingle();
      await confirm();

      fixture.destroy();
      await tick();
      const [op, ...again] = apollo.match(DeleteVideoDocument);
      expect(again).toHaveLength(0);

      op.flushData({ deleteVideo: { __typename: 'VideoMutationResult', success: true, video: null } });
      await tick();
      expect(videosDeleted).toHaveBeenCalledExactlyOnceWith(['v1']);
    });
  });

  describe('selected videos', () => {
    it('deletes the selection from its directory and announces each video', async () => {
      /*
        Given the panel is opened to delete the 2 selected videos "v1" and "v2" in "local/movies"
        Then it asks whether to delete the selected 2 videos
        When the user confirms
        Then one batch deletion of "v1" and "v2" in "local/movies" is sent
        When the backend reports "Deleting 1/2"
        Then that progress is shown and "Yes" is disabled
        When the backend reports success
        Then "v1" and "v2" are announced as deleted and the panel closes reporting success
      */
      await openBatch();
      expect(text()).toContain('Are you sure you want to delete the selected 2 videos?');

      await confirm();
      const op = apollo.expectOne(BatchDeleteSubscriptionDocument);
      expect(op.operation.variables['input']).toEqual({
        videoIds: ['v1', 'v2'],
        relativePath: { relativePath: 'local/movies' },
      });

      op.flushData(batchFrame('Deleting 1/2', null));
      await settle();
      expect(text()).toContain('Deleting 1/2');
      expect(await (await yes()).isDisabled()).toBe(true);

      await reportResult(op, BatchResultType.Success);
      expect(videosDeleted).toHaveBeenCalledExactlyOnceWith(['v1', 'v2']);
      expect(directoryDeleted).not.toHaveBeenCalled();
      expect(toast).toHaveBeenCalledExactlyOnceWith('Batch delete completed successfully.', ToastType.Success);
      expect(close).toHaveBeenCalledExactlyOnceWith(true);
    });

    it('announces the deletion with a warning when only some videos were deleted', async () => {
      /*
        Given the user has confirmed deleting the selected videos "v1" and "v2"
        When the backend reports partial success with "Deleted 1 out of 2 videos"
        Then "v1" and "v2" are announced as deleted
        And a warning toast includes "Deleted 1 out of 2 videos" and the panel closes reporting success
      */
      await reportResult(await confirmedBatch(), BatchResultType.PartialSuccess, 'Deleted 1 out of 2 videos');

      expect(videosDeleted).toHaveBeenCalledExactlyOnceWith(['v1', 'v2']);
      expect(toast).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('Deleted 1 out of 2 videos'), ToastType.Warning);
      expect(close).toHaveBeenCalledExactlyOnceWith(true);
    });

    it('closes reporting failure with the reason when nothing was deleted', async () => {
      /*
        Given the user has confirmed deleting the selected videos "v1" and "v2"
        When the backend reports a failure with "Deleted 0 out of 2 videos"
        Then an error toast includes "Deleted 0 out of 2 videos", nothing is announced
        And the panel closes reporting failure
      */
      await reportResult(await confirmedBatch(), BatchResultType.Failure, 'Deleted 0 out of 2 videos');

      expect(toast).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('Deleted 0 out of 2 videos'), ToastType.Error);
      expect(videosDeleted).not.toHaveBeenCalled();
      expect(close).toHaveBeenCalledExactlyOnceWith(false);
    });

    it('closes reporting failure when the deletion cannot reach the backend', async () => {
      /*
        Given the user has confirmed deleting the selected videos "v1" and "v2"
        When the request fails with a network error
        Then an error toast says the batch delete failed
        And the panel closes reporting failure instead of staying busy
      */
      const op = await confirmedBatch();

      op.networkError(new Error('connection lost'));
      await settle();

      expect(toast).toHaveBeenCalledWith(expect.stringContaining('Batch delete failed'), ToastType.Error);
      expect(videosDeleted).not.toHaveBeenCalled();
      expect(close).toHaveBeenCalledExactlyOnceWith(false);
    });
  });

  describe('a whole directory', () => {
    it('keeps the folder by default and announces the directory as emptied', async () => {
      /*
        Given the panel is opened to delete everything in "local/old"
        Then it asks whether to delete everything in "local/old"
        And keeping the folder is preselected
        When the user confirms
        Then a batch deletion of directory "local/old" with no video ids is sent, keeping the folder
        When the backend reports success
        Then directory "local/old" is announced as deleted
      */
      await openDirectory();
      expect(text()).toContain('Are you sure you want to delete everything in the directory "local/old"?');
      const keep = await loader.getHarness(MatRadioButtonHarness.with({ label: /keep the folder/ }));
      expect(await keep.isChecked()).toBe(true);

      await confirm();
      const op = apollo.expectOne(BatchDeleteSubscriptionDocument);
      expect(op.operation.variables['input']).toEqual({
        videoIds: [],
        relativePath: { relativePath: 'local/old' },
        directoryDeletion: DirectoryDeletionStrategy.KeepFolder,
      });

      await reportResult(op, BatchResultType.Success);
      expect(directoryDeleted).toHaveBeenCalledExactlyOnceWith('local/old');
      expect(videosDeleted).not.toHaveBeenCalled();
    });

    it('deletes the folder too when asked', async () => {
      /*
        Given the panel is opened to delete everything in "local/old"
        When the user chooses to delete the folder too and confirms
        Then the batch deletion asks for the folder to be deleted
      */
      await openDirectory();

      await (await loader.getHarness(MatRadioButtonHarness.with({ label: /Delete the folder too/ }))).check();
      await confirm();

      expect(apollo.expectOne(BatchDeleteSubscriptionDocument).operation.variables['input'].directoryDeletion)
        .toBe(DirectoryDeletionStrategy.DeleteFolder);
    });
  });

  it('sends nothing when neither videos nor a directory are named', async () => {
    /*
      Given the panel is opened for a directory deletion without a directory
      When the user confirms
      Then an error toast is shown, no deletion is sent and the panel closes reporting failure
    */
    await openPanel({ deleteType: DeleteType.Directory });

    await confirm();

    expect(toast).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('No videoIds or directoryPath'), ToastType.Error);
    apollo.expectNone(BatchDeleteSubscriptionDocument);
    expect(close).toHaveBeenCalledExactlyOnceWith(false);
  });
});
