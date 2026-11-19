import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatRadioButtonHarness } from '@angular/material/radio/testing';
import { MatSlideToggleHarness } from '@angular/material/slide-toggle/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { ApolloTestingController, ApolloTestingModule, TestOperation } from 'apollo-angular/testing';
import { MockInstance } from 'vitest';

import { BatchOperationPanel } from './batch-operation-panel';
import { BatchPanelData, BatchPanelVideoItem } from '../../models/panels.model';
import { ToastType } from '../../models/toast.model';
import { ToastService } from '../../../services/toast-service/toast.service';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import { BatchResultType, BatchUpdateSubscriptionDocument } from '../../../core/graphql/generated/graphql';
import { apolloAsInTheApp } from '../../../../testing/apollo-testing';

/** Apollo hands results to subscribers asynchronously. */
const tick = () => new Promise<void>(resolve => setTimeout(resolve));

const item = (id: string, seriesName: string | null = null, seriesOrder: number | null = null): BatchPanelVideoItem =>
  ({ id, name: id, seriesName, seriesOrder });

const forVideos = (...items: BatchPanelVideoItem[]): BatchPanelData =>
  ({ mode: 'videos', videos: new Set(items.map(i => i.id)), videoItems: items });

describe('BatchOperationPanel', () => {
  let fixture: ComponentFixture<BatchOperationPanel>;
  let loader: HarnessLoader;
  let apollo: ApolloTestingController;
  let close: ReturnType<typeof vi.fn>;
  let toast: MockInstance<ToastService['emitNewToast']>;
  let announced: MockInstance<VideoUpdateEventService['emitUpdated']>;

  async function openPanel(data: BatchPanelData) {
    TestBed.resetTestingModule();
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [BatchOperationPanel, ApolloTestingModule],
      providers: [
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
    announced = vi.spyOn(TestBed.inject(VideoUpdateEventService), 'emitUpdated').mockImplementation(() => {});

    fixture = TestBed.createComponent(BatchOperationPanel);
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
  const input = (placeholder: string) => element().querySelector<HTMLInputElement>(`input[placeholder="${placeholder}"]`)!;

  async function type(placeholder: string, value: string) {
    const field = input(placeholder);
    field.value = value;
    field.dispatchEvent(new Event('input'));
    await settle();
  }

  const typeCreator = (name: string) => type('search', name);
  const typeSeriesName = (name: string) => type('Search or type a new series name', name);

  async function enterTag(list: 'add' | 'remove', tag: string) {
    await type(`Enter a tag to ${list}`, tag);
    input(`Enter a tag to ${list}`).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
  }

  const chips = (list: 'add' | 'remove') => {
    const [add, remove] = element().querySelectorAll('app-tag-chip-input');
    return [...(list === 'add' ? add : remove).querySelectorAll('mat-chip')].map(chip => chip.textContent!.replace('cancel', '').trim());
  };

  async function removeChip(tag: string) {
    element().querySelector<HTMLButtonElement>(`button[aria-label="Remove ${tag}"]`)!.click();
    await settle();
  }

  async function modifySeries() {
    await (await loader.getHarness(MatSlideToggleHarness.with({ label: /Modify series/ }))).toggle();
    await settle();
  }

  async function chooseClear() {
    await (await loader.getHarness(MatRadioButtonHarness.with({ label: /Clear/ }))).check();
    await settle();
  }

  const reorderRows = () => [...element().querySelectorAll('app-series-reorder-list li')];
  const reorderList = () => reorderRows().map(row => row.querySelector('span.flex-1')!.textContent!.trim());

  async function moveUp(name: string) {
    const row = reorderRows().find(r => r.querySelector('span.flex-1')!.textContent!.trim() === name)!;
    row.querySelector<HTMLButtonElement>('button[aria-label="Move up"]')!.click();
    await settle();
  }

  const button = (label: RegExp) => loader.getHarness(MatButtonHarness.with({ text: label }));
  const SAVE = /^(Edit|Sync Directory)$/;
  const isEnabled = async (label: RegExp) => !(await (await button(label)).isDisabled());

  async function press(label: RegExp) {
    await (await button(label)).click();
    await settle();
  }

  // ─── Backend answers ───────────────────────────────────────────────

  /** Saves and returns the update that was sent, still open for answers. */
  async function save(): Promise<TestOperation> {
    await press(SAVE);
    return apollo.expectOne(BatchUpdateSubscriptionDocument);
  }

  const sentInput = async () => (await save()).operation.variables['input'];

  async function reportProgress(op: TestOperation, status: string) {
    op.flushData({ batchUpdateSubscription: { __typename: 'BatchOperationStatus', status, result: null } });
    await settle();
  }

  async function reportResult(op: TestOperation, resultType: BatchResultType, message = 'done') {
    op.flushData({
      batchUpdateSubscription: {
        __typename: 'BatchOperationStatus',
        status: null,
        result: { __typename: 'VideosBatchOperationResult', resultType, message },
      },
    });
    await settle();
  }

  /** Opens the panel for two videos with a creator typed, ready to save. */
  async function readyToSave() {
    await openPanel(forVideos(item('v1'), item('v2')));
    await typeCreator('bob');
  }

  // ─── Scenarios ─────────────────────────────────────────────────────

  describe('editing selected videos', () => {
    it('cannot be saved until something would change', async () => {
      /*
        Given the panel is opened for videos "v1" and "v2"
        Then "Edit" is disabled
        When the user turns on "Modify series" but leaves the series name blank
        Then "Edit" is still disabled
        When the user types the creator "  bob  "
        Then "Edit" is enabled
      */
      await openPanel(forVideos(item('v1'), item('v2')));
      expect(text()).toContain('2 video(s) selected');
      expect(await isEnabled(SAVE)).toBe(false);

      await modifySeries();
      expect(await isEnabled(SAVE)).toBe(false);

      await typeCreator('  bob  ');
      expect(await isEnabled(SAVE)).toBe(true);
    });

    it('sends the creator, the tags to add and the tags to remove in one update', async () => {
      /*
        Given the panel is opened for videos "v1" and "v2"
        When the user types the creator "  bob  ", adds tag "new" and removes tag "old"
        And saves
        Then one batch update is sent for "v1" and "v2" without a directory
        And it carries the creator "bob", adds ["new"], removes ["old"] and has no series operation
      */
      await openPanel(forVideos(item('v1'), item('v2')));
      await typeCreator('  bob  ');
      await enterTag('add', 'new');
      await enterTag('remove', 'old');

      expect(await sentInput()).toEqual({
        videoIds: ['v1', 'v2'],
        relativePath: {},
        tagsOperation: { addTags: ['new'], removeTags: ['old'] },
        author: 'bob',
      });
    });

    it('refuses a tag that is already on the other list until it leaves that list', async () => {
      /*
        Given the user has put tag "drama" on the remove list
        When the user tries to add "drama" to the add list
        Then "drama" is not added and a warning says it is already on the other list
        When the user takes "drama" off the remove list
        Then the warning disappears
        And "drama" can now be added
      */
      await openPanel(forVideos(item('v1'), item('v2')));
      await enterTag('remove', 'drama');

      await enterTag('add', 'drama');
      expect(chips('add')).toEqual([]);
      expect(text()).toContain('"drama" is already on the other list');

      await removeChip('drama');
      expect(text()).not.toContain('already on the other list');

      await enterTag('add', 'drama');
      expect(chips('add')).toEqual(['drama']);
      expect(chips('remove')).toEqual([]);
    });

    it('describes the series the selection is in now', async () => {
      /*
        Given the selection is "a" and "b", both in series "Saga"
        Then the panel says all 2 selected videos are in series "Saga"
        Given instead "a" is in "Saga" and "b" is in no series
        Then the panel says they span 1 series (Saga) and videos with none
        Given instead "a" is in "Saga" and "b" is in "Epic"
        Then the panel says they span 2 series (Epic, Saga), without mentioning videos with none
        Given instead neither video is in a series
        Then the panel says none of the selected videos belong to a series
      */
      await openPanel(forVideos(item('a', 'Saga', 1), item('b', 'Saga', 2)));
      expect(text()).toContain('All 2 selected videos are in series "Saga".');

      await openPanel(forVideos(item('a', 'Saga', 1), item('b')));
      expect(text()).toContain('Selected videos span 1 series (Saga) and videos with none.');

      await openPanel(forVideos(item('a', 'Saga', 1), item('b', 'Epic', 1)));
      expect(text()).toContain('Selected videos span 2 series (Epic, Saga).');
      expect(text()).not.toContain('videos with none');

      await openPanel(forVideos(item('a'), item('b')));
      expect(text()).toContain('None of the selected videos belong to a series.');
    });

    it('reorders a series the whole selection already shares', async () => {
      /*
        Given "a" is 2nd, "b" is 1st and "c" is 3rd in series "Saga"
        When the user turns on "Modify series"
        Then the series name is already "Saga" and no move warning is shown
        And the videos are listed "b", "a", "c"
        When the user moves "c" up and saves
        Then the update sets series "Saga" with the order b=1, c=2, a=3
      */
      await openPanel(forVideos(item('a', 'Saga', 2), item('b', 'Saga', 1), item('c', 'Saga', 3)));

      await modifySeries();
      expect(input('Search or type a new series name').value).toBe('Saga');
      expect(text()).not.toContain('Saving will move');
      expect(reorderList()).toEqual(['b', 'a', 'c']);

      await moveUp('c');
      expect((await sentInput()).seriesOperation).toEqual({
        clear: false,
        name: 'Saga',
        orders: [{ videoId: 'b', order: 1 }, { videoId: 'c', order: 2 }, { videoId: 'a', order: 3 }],
      });
    });

    it('warns before moving videos out of the series they are in', async () => {
      /*
        Given "a" is 2nd in series "Saga", "b" is 1st in "Epic", and "d" and "c" are in none
        When the user turns on "Modify series" and names the series "Saga"
        Then a warning says the videos currently belong to "Epic" and will move into "Saga"
        When the user names the series "New"
        Then a warning says the videos span 2 series (Epic, Saga) and will all move into "New"
        When the user saves
        Then the update sets series "New", listing videos in series order first and then by name
      */
      await openPanel(forVideos(item('d'), item('c'), item('a', 'Saga', 2), item('b', 'Epic', 1)));
      await modifySeries();

      await typeSeriesName('Saga');
      expect(text()).toContain('Selected videos currently belong to series "Epic". Saving will move them into "Saga".');

      await typeSeriesName('New');
      expect(text()).toContain(
        'Selected videos currently span 2 series (Epic, Saga). Saving will move them all into "New".');

      expect((await sentInput()).seriesOperation).toEqual({
        clear: false,
        name: 'New',
        orders: ['b', 'a', 'c', 'd'].map((videoId, i) => ({ videoId, order: i + 1 })),
      });
    });

    it('clears the series of every selected video', async () => {
      /*
        Given "a" and "b" are in series "Saga"
        When the user turns on "Modify series", chooses "Clear" and saves
        Then the update clears the series and carries nothing else
      */
      await openPanel(forVideos(item('a', 'Saga', 1), item('b', 'Saga', 2)));
      await modifySeries();
      await chooseClear();
      expect(text()).toContain('Series will be removed from all selected videos.');

      // Only the series changes: no tag lists, creator or order ride along.
      expect(await sentInput()).toEqual({ videoIds: ['a', 'b'], relativePath: {}, seriesOperation: { clear: true } });
    });
  });

  describe('syncing a directory', () => {
    it('updates every video in the directory, without series options', async () => {
      /*
        Given the panel is opened for directory "local/movies"
        Then it names the directory and offers no series options
        And "Sync Directory" is enabled even with nothing filled in
        When the user adds tag "film" and syncs
        Then one batch update is sent for directory "local/movies" with no video ids
        And it adds ["film"] and has no series operation
      */
      await openPanel({ mode: 'directory', selectedDirectoryPath: 'local/movies' });
      expect(text()).toContain('All videos in Directory: local/movies');
      expect(await loader.getAllHarnesses(MatSlideToggleHarness)).toHaveLength(0);
      expect(await isEnabled(SAVE)).toBe(true);

      await enterTag('add', 'film');

      expect(await sentInput()).toEqual({
        videoIds: [],
        relativePath: { relativePath: 'local/movies' },
        tagsOperation: { addTags: ['film'], removeTags: [] },
      });
    });
  });

  describe('running the update', () => {
    it('shows progress and locks the buttons until the update ends', async () => {
      /*
        Given the user has saved an update
        When the backend reports "Updating 1/2"
        Then that progress is shown and "Edit" and "Cancel" are disabled
      */
      await readyToSave();
      const op = await save();

      await reportProgress(op, 'Updating 1/2');

      expect(text()).toContain('Updating 1/2');
      expect(await isEnabled(/^Edit/)).toBe(false);
      expect(await isEnabled(/Cancel/)).toBe(false);
    });

    it('closes and announces the change when every video was updated', async () => {
      /*
        Given the user has saved an update for "v1" and "v2"
        When the backend reports success
        Then "v1" and "v2" are announced as updated
        And a success toast is shown and the panel closes reporting success
      */
      await readyToSave();

      await reportResult(await save(), BatchResultType.Success);

      expect(announced).toHaveBeenCalledExactlyOnceWith(['v1', 'v2']);
      expect(toast).toHaveBeenCalledExactlyOnceWith('Batch update completed successfully.', ToastType.Success);
      expect(close).toHaveBeenCalledExactlyOnceWith(true);
    });

    it('closes with a warning carrying the reason when only some videos were updated', async () => {
      /*
        Given the user has saved an update for "v1" and "v2"
        When the backend reports partial success with "1 of 2 updated"
        Then "v1" and "v2" are announced as updated
        And a warning toast includes "1 of 2 updated" and the panel closes reporting success
      */
      await readyToSave();

      await reportResult(await save(), BatchResultType.PartialSuccess, '1 of 2 updated');

      expect(announced).toHaveBeenCalledExactlyOnceWith(['v1', 'v2']);
      expect(toast).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('1 of 2 updated'), ToastType.Warning);
      expect(close).toHaveBeenCalledExactlyOnceWith(true);
    });

    it('stays open for another try when nothing needed changing', async () => {
      /*
        Given the user has saved an update
        When the backend reports everything was already up to date
        Then a warning toast says no changes were made
        And the panel stays open with "Edit" enabled again and nothing announced
      */
      await readyToSave();

      await reportResult(await save(), BatchResultType.AlreadyUpToDate);

      expect(toast).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('No changes were made'), ToastType.Warning);
      expect(close).not.toHaveBeenCalled();
      expect(announced).not.toHaveBeenCalled();
      expect(await isEnabled(SAVE)).toBe(true);
    });

    it('stays open and shows the reason when the backend reports a failure', async () => {
      /*
        Given the user has saved an update
        When the backend reports a failure with "No video IDs or file entries provided"
        Then an error toast includes "No video IDs or file entries provided"
        And the panel stays open with "Edit" enabled again and nothing announced
      */
      await readyToSave();

      await reportResult(await save(), BatchResultType.Failure, 'No video IDs or file entries provided');

      expect(toast).toHaveBeenCalledExactlyOnceWith(
        expect.stringContaining('No video IDs or file entries provided'), ToastType.Error);
      expect(close).not.toHaveBeenCalled();
      expect(announced).not.toHaveBeenCalled();
      expect(await isEnabled(SAVE)).toBe(true);
    });

    it('stays open when the update cannot reach the backend', async () => {
      /*
        Given the user has saved an update
        When the request fails with a network error
        Then an error toast says the batch update failed
        And the panel stays open with "Edit" enabled again
      */
      await readyToSave();
      const op = await save();

      op.networkError(new Error('connection lost'));
      await settle();

      expect(toast).toHaveBeenCalledWith('Batch update failed. Please try again.', ToastType.Error);
      expect(close).not.toHaveBeenCalled();
      expect(await isEnabled(SAVE)).toBe(true);
    });
  });

  it('closes without saving on cancel', async () => {
    /*
      Given the panel is opened for videos "v1" and "v2"
      When the user cancels
      Then the panel closes without reporting success and no update is sent
    */
    await readyToSave();

    await press(/Cancel/);

    expect(close).toHaveBeenCalledExactlyOnceWith();
    apollo.expectNone(BatchUpdateSubscriptionDocument);
  });
});
