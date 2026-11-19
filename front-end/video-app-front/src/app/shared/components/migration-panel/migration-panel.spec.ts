import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatRadioButtonHarness } from '@angular/material/radio/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';
import { MockInstance } from 'vitest';

import { MigrationPanel } from './migration-panel';
import { MigrationPanelData, MigrationSourceVideo } from '../../models/panels.model';
import { ToastType } from '../../models/toast.model';
import { ToastService } from '../../../services/toast-service/toast.service';
import { MigrationTrackerService } from '../../../services/migration-tracker-service/migration-tracker.service';
import {
  BrowseDirectoryDocument,
  CreateMigrationBatchDocument,
  CreateMigrationTaskDocument,
  MigrationBatchPreflightDocument,
  MigrationPreflightDocument,
} from '../../../core/graphql/generated/graphql';
import { aMigrationTask } from '../../../../testing/migration-fixtures';
import { aBrowseNode } from '../../../../testing/video-fixtures';
import { apolloAsInTheApp } from '../../../../testing/apollo-testing';

/** Apollo hands results to subscribers asynchronously. */
const tick = () => new Promise<void>(resolve => setTimeout(resolve));

const folder = (name: string) => aBrowseNode({ id: `dir-${name}`, isDir: true, name });
const video = (id: string, name = `${id}.mp4`): MigrationSourceVideo => ({ id, name, size: 1000 });

const preflightResult = (overrides: Record<string, unknown> = {}) => ({
  __typename: 'MigrationPreflightResult',
  valid: true,
  sourceFileSize: '1000',
  conflictExists: false,
  spaceAvailable: '1000000',
  spaceSufficient: true,
  alreadyMigrating: false,
  sameLocation: false,
  errorMessage: null,
  ...overrides,
});

const batchItem = (sourceVideoId: string, overrides: Record<string, unknown> = {}) => {
  const { spaceAvailable, spaceSufficient, ...result } = preflightResult(overrides);
  return { __typename: 'MigrationBatchPreflightItem', sourceVideoId, result };
};

const ready = (id: string) => batchItem(id);
const conflicting = (id: string) => batchItem(id, { conflictExists: true });
const alreadyThere = (id: string) =>
  batchItem(id, { valid: false, sameLocation: true, errorMessage: 'source path and target path are the same' });
const alreadyMigrating = (id: string) =>
  batchItem(id, { valid: false, alreadyMigrating: true, errorMessage: 'the file already has an active migration task' });

describe('MigrationPanel', () => {
  let fixture: ComponentFixture<MigrationPanel>;
  let loader: HarnessLoader;
  let apollo: ApolloTestingController;
  let close: ReturnType<typeof vi.fn>;
  let toast: MockInstance<ToastService['emitNewToast']>;
  let track: MockInstance<MigrationTrackerService['track']>;
  let trackBatch: MockInstance<MigrationTrackerService['trackBatch']>;

  async function openPanel(videos: MigrationSourceVideo[], sourceCurrentDir = 'local/src') {
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [MigrationPanel, ApolloTestingModule],
      providers: [
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { videos, sourceCurrentDir } satisfies MigrationPanelData },
      ],
    });
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
    const tracker = TestBed.inject(MigrationTrackerService);
    track = vi.spyOn(tracker, 'track').mockImplementation(() => {});
    trackBatch = vi.spyOn(tracker, 'trackBatch').mockImplementation(() => {});

    fixture = TestBed.createComponent(MigrationPanel);
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

  const folderButtons = () =>
    [...element().querySelectorAll('button')].filter(b => b.querySelector('mat-icon[fonticon="folder"]'));
  const shownFolders = () => folderButtons().map(b => b.textContent!.replace('folder', '').trim());

  const breadcrumbButtons = () =>
    [...element().querySelector('mat-icon[fonticon="home"]')!.closest('div')!.querySelectorAll('button')];
  const breadcrumb = () => breadcrumbButtons().slice(1).map(b => b.textContent!.trim());

  async function openFolder(name: string) {
    folderButtons().find(b => b.textContent!.includes(name))!.click();
    await settle();
  }

  async function typeFilter(keyword: string) {
    const input = element().querySelector<HTMLInputElement>('input[placeholder="Filter folders"]')!;
    input.value = keyword;
    input.dispatchEvent(new Event('input'));
    await settle();
  }

  const filterValue = () => element().querySelector<HTMLInputElement>('input[placeholder="Filter folders"]')!.value;

  async function toggleSort() {
    [...element().querySelectorAll('button')].find(b => b.textContent!.trim().endsWith('Name'))!.click();
    await settle();
  }

  const button = (label: string) => loader.getHarness(MatButtonHarness.with({ text: new RegExp(label) }));
  const isEnabled = async (label: string) => !(await (await button(label)).isDisabled());

  async function press(label: string) {
    await (await button(label)).click();
    await settle();
  }

  async function pickStrategy(label: 'Rename' | 'Overwrite' | 'Skip') {
    await (await loader.getHarness(MatRadioButtonHarness.with({ label: new RegExp(label) }))).check();
    await settle();
  }

  const checkedStrategy = async () => {
    for (const radio of await loader.getAllHarnesses(MatRadioButtonHarness)) {
      if (await radio.isChecked()) return radio.getValue();
    }
    return null;
  };

  // ─── Backend answers ───────────────────────────────────────────────

  async function answerListing(...entries: ReturnType<typeof aBrowseNode>[]) {
    const op = apollo.expectOne(BrowseDirectoryDocument);
    op.flushData({ browseDirectory: entries });
    await settle();
    return op.operation.variables['input'];
  }

  /** Walks from the root to `path`, one listing per level, and selects it. */
  async function chooseTarget(...path: string[]) {
    for (const name of path) {
      await answerListing(folder(name));
      await openFolder(name);
    }
    await answerListing();
    await press('Select this directory');
  }

  async function answerPreflight(overrides: Record<string, unknown> = {}) {
    await press('Preflight Check');
    const op = apollo.expectOne(MigrationPreflightDocument);
    op.flushData({ migrationPreflight: preflightResult(overrides) });
    await settle();
    return op.operation.variables['input'];
  }

  async function answerBatchPreflight(
    items: ReturnType<typeof batchItem>[],
    space: { spaceSufficient: boolean | null } = { spaceSufficient: true },
  ) {
    await press('Preflight Check');
    const op = apollo.expectOne(MigrationBatchPreflightDocument);
    op.flushData({
      migrationBatchPreflight: {
        __typename: 'MigrationBatchPreflightResult',
        valid: items.every(item => item.result.valid) && space.spaceSufficient !== false,
        totalSize: String(items.length * 1000),
        spaceAvailable: space.spaceSufficient === false ? '500' : '1000000',
        spaceSufficient: space.spaceSufficient,
        items,
      },
    });
    await settle();
  }

  async function startAndAnswerTask(answer: { success: boolean; errorMessage?: string }) {
    await press('Start Migration');
    const op = apollo.expectOne(CreateMigrationTaskDocument);
    const task = aMigrationTask();
    op.flushData({
      createMigrationTask: {
        __typename: 'MigrationTaskMutationResult',
        success: answer.success,
        errorMessage: answer.errorMessage ?? null,
        task: answer.success ? task : null,
      },
    });
    await settle();
    return { input: op.operation.variables['input'], task };
  }

  async function startAndAnswerBatch(answer: {
    batchId: string | null;
    created: number;
    skipped?: { sourceVideoId: string; reason: string }[];
  }) {
    await press('Start Migration');
    const op = apollo.expectOne(CreateMigrationBatchDocument);
    const tasks = Array.from({ length: answer.created }, () => aMigrationTask({ batchId: answer.batchId }));
    op.flushData({
      createMigrationBatch: {
        __typename: 'CreateMigrationBatchResult',
        batchId: answer.batchId,
        tasks,
        skipped: (answer.skipped ?? []).map(skip => ({ __typename: 'SkippedMigrationSource', ...skip })),
      },
    });
    await settle();
    return { input: op.operation.variables['input'], tasks };
  }

  const sentInput = async (document: typeof CreateMigrationBatchDocument) => {
    await press('Start Migration');
    return apollo.expectOne(document).operation.variables['input'];
  };

  // ─── Scenarios ─────────────────────────────────────────────────────

  describe('choosing the target directory', () => {
    it('opens on the root listing and shows only folders, A to Z', async () => {
      /*
        Given the panel is opened for one video
        When the root listing arrives with folders "b-dir" and "A-dir" and a video file "clip.mp4"
        Then the root was listed without cache and without recursive size calculation
        And the list shows "A-dir" then "b-dir"
        And no video file is listed
      */
      await openPanel([video('v1')]);

      const listed = await answerListing(folder('b-dir'), folder('A-dir'), aBrowseNode({ name: 'clip.mp4' }));

      expect(listed).toEqual({ relativePath: undefined, skipCache: true, recursiveCalculation: false });
      expect(shownFolders()).toEqual(['A-dir', 'b-dir']);
      expect(text()).not.toContain('clip.mp4');
    });

    it('walks into folders and back through the breadcrumb', async () => {
      /*
        Given the root listing shows folder "local"
        When the user opens "local" and then its folder "movies"
        Then "local/movies" is listed and the breadcrumb shows "local" and "movies"
        When the user clicks "local" in the breadcrumb
        Then "local" is listed again
      */
      await openPanel([video('v1')]);
      await answerListing(folder('local'));

      await openFolder('local');
      expect((await answerListing(folder('movies'))).relativePath).toBe('local');
      await openFolder('movies');
      expect((await answerListing()).relativePath).toBe('local/movies');
      expect(breadcrumb()).toEqual(['local', 'movies']);

      breadcrumbButtons()[1].click();
      await settle();
      expect(breadcrumb()).toEqual(['local']);
      expect((await answerListing(folder('movies'))).relativePath).toBe('local');
      expect(shownFolders()).toEqual(['movies']);
    });

    it('ignores a listing that arrives after the user has moved on', async () => {
      /*
        Given the user opened folder "slow" from the root
        When the user goes back to the root before "slow" has been listed
        And the listing for "slow" arrives late
        Then the root listing is still shown
      */
      await openPanel([video('v1')]);
      await answerListing(folder('slow'), folder('other'));
      await openFolder('slow');
      const slow = apollo.expectOne(BrowseDirectoryDocument);

      breadcrumbButtons()[0].click();
      await settle();
      await answerListing(folder('slow'), folder('other'));
      slow.flushData({ browseDirectory: [folder('inside-slow')] });
      await settle();

      expect(breadcrumb()).toEqual([]);
      expect(shownFolders()).toEqual(['other', 'slow']);
    });

    it('filters folders by a case-insensitive keyword and resets it on navigation', async () => {
      /*
        Given a listing with folders "Movies", "MUSIC" and "Photos"
        When the user types "mu" into the folder filter
        Then only "MUSIC" is shown
        When the user types "zzz"
        Then the list says there are no matching folders
        When the user opens a folder
        Then the filter is empty again
      */
      await openPanel([video('v1')]);
      await answerListing(folder('Movies'), folder('MUSIC'), folder('Photos'));

      await typeFilter('mu');
      expect(shownFolders()).toEqual(['MUSIC']);

      await typeFilter('zzz');
      expect(shownFolders()).toEqual([]);
      expect(text()).toContain('No matching folders');

      await typeFilter('mu');
      await openFolder('MUSIC');
      await answerListing(folder('jazz'));
      expect(filterValue()).toBe('');
      expect(shownFolders()).toEqual(['jazz']);
    });

    it('sorts folders Z to A on request and keeps that order in other folders', async () => {
      /*
        Given a listing with folders "a", "b" and "c"
        When the user toggles the sort
        Then the folders are shown "c", "b", "a"
        When the user opens "c" and it holds folders "x" and "y"
        Then they are shown "y", "x"
      */
      await openPanel([video('v1')]);
      await answerListing(folder('b'), folder('a'), folder('c'));

      await toggleSort();
      expect(shownFolders()).toEqual(['c', 'b', 'a']);

      await openFolder('c');
      await answerListing(folder('x'), folder('y'));
      expect(shownFolders()).toEqual(['y', 'x']);
    });

    it('only allows a preflight check once a folder below the root is chosen', async () => {
      /*
        Given the panel shows the root listing
        Then "Select this directory" and "Preflight Check" are disabled
        When the user opens "local", then "movies", and selects it
        Then the target "local/movies" is shown
        And "Preflight Check" is enabled
      */
      await openPanel([video('v1')]);
      await answerListing(folder('local'));

      expect(await isEnabled('Select this directory')).toBe(false);
      expect(await isEnabled('Preflight Check')).toBe(false);

      await openFolder('local');
      await answerListing(folder('movies'));
      await openFolder('movies');
      await answerListing();
      await press('Select this directory');

      expect(text()).toContain('Target: local/movies');
      expect(await isEnabled('Preflight Check')).toBe(true);
    });
  });

  describe('moving one video', () => {
    beforeEach(async () => {
      await openPanel([video('v1', 'clip.mp4')]);
      await chooseTarget('local', 'dst');
    });

    it('starts a migration when every check passes', async () => {
      /*
        Given video "v1" in "local/src" and target "local/dst" is chosen
        When the preflight check finds no problem
        Then the panel says all checks passed and "Start Migration" is enabled
        When the user starts the migration
        Then a migration of "v1" to "local/dst" is created without a conflict strategy
        And the new task is tracked, a success toast is shown, and the panel closes reporting success
      */
      const checked = await answerPreflight();
      expect(checked).toEqual({ sourceVideoId: 'v1', targetDirRelativePath: { relativePath: 'local/dst' } });
      expect(text()).toContain('All checks passed');
      expect(await isEnabled('Start Migration')).toBe(true);

      const { input, task } = await startAndAnswerTask({ success: true });

      expect(input).toEqual({ sourceVideoId: 'v1', targetDirRelativePath: { relativePath: 'local/dst' } });
      expect(track).toHaveBeenCalledExactlyOnceWith([task]);
      expect(toast).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('created successfully'), ToastType.Success);
      expect(close).toHaveBeenCalledExactlyOnceWith(true);
    });

    it('asks how to handle a namesake, defaulting to rename', async () => {
      /*
        Given a target is chosen
        When the preflight check finds a file with the same name in the target
        Then rename is preselected and "Start Migration" is enabled
        When the user picks skip
        Then "Start Migration" is disabled
        When the user picks overwrite and starts the migration
        Then the migration is created with the overwrite strategy
      */
      await answerPreflight({ conflictExists: true });
      expect(await checkedStrategy()).toBe('rename');
      expect(await isEnabled('Start Migration')).toBe(true);

      await pickStrategy('Skip');
      expect(await isEnabled('Start Migration')).toBe(false);

      await pickStrategy('Overwrite');
      const { input } = await startAndAnswerTask({ success: true });
      expect(input.conflictStrategy).toBe('overwrite');
    });

    it('blocks a video that failed a check', async () => {
      /*
        Given a target is chosen
        When the preflight check reports the video is already being migrated
        Then the panel says so and "Start Migration" is disabled
      */
      await answerPreflight({
        valid: false,
        alreadyMigrating: true,
        errorMessage: 'the file already has an active migration task',
      });

      expect(text()).toContain('This file is already being migrated');
      expect(await isEnabled('Start Migration')).toBe(false);
    });

    it('blocks a video that failed a check even when it also has a namesake', async () => {
      /*
        Given a target is chosen
        When the preflight check reports insufficient space and a file with the same name in the target
        Then "Start Migration" is disabled whichever conflict strategy is picked
      */
      await answerPreflight({
        valid: false,
        conflictExists: true,
        spaceSufficient: false,
        spaceAvailable: '10',
        errorMessage: 'insufficient space available at the target location',
      });

      for (const strategy of ['Rename', 'Overwrite', 'Skip'] as const) {
        await pickStrategy(strategy);
        expect(await isEnabled('Start Migration'), strategy).toBe(false);
      }
    });

    it('stays open and shows the reason when the migration cannot be created', async () => {
      /*
        Given the preflight check passed
        When the user starts the migration and creation fails with "file is locked"
        Then an error toast says "file is locked"
        And the panel stays open and tracks nothing
      */
      await answerPreflight();

      await startAndAnswerTask({ success: false, errorMessage: 'file is locked' });

      expect(toast).toHaveBeenCalledExactlyOnceWith('file is locked', ToastType.Error);
      expect(close).not.toHaveBeenCalled();
      expect(track).not.toHaveBeenCalled();
    });

    it('goes back to choosing a target with the choice kept and the strategy dropped', async () => {
      /*
        Given the preflight check found a namesake and the user picked overwrite
        When the user goes back
        Then the folder list is shown again with the chosen target still shown
        When the user runs the check again and the namesake is gone
        And the user starts the migration
        Then the migration is created without a conflict strategy
      */
      await answerPreflight({ conflictExists: true });
      await pickStrategy('Overwrite');

      await press('Back');
      expect(text()).toContain('Select target directory');
      expect(text()).toContain('Target: local/dst');

      await answerPreflight();
      const { input } = await startAndAnswerTask({ success: true });
      expect(input.conflictStrategy).toBeUndefined();
    });
  });

  describe('moving several videos', () => {
    const names = ['a', 'b', 'c', 'd', 'e', 'f'];

    async function openBatch(count: number) {
      await openPanel(names.slice(0, count).map(n => video(n, `${n}.mp4`)));
      await chooseTarget('local', 'dst');
    }

    it('sorts the files into ready, conflicting and left out', async () => {
      /*
        Given six videos are moved to "local/dst"
        When the batch preflight check finds two ready, two with a namesake,
          one already in the target and one already being migrated, with enough space in total
        Then the panel says 2 files are ready and 2 have a namesake, naming the two
        And it says 2 files will be left out, naming each with its reason
        And rename is preselected
      */
      await openBatch(6);

      await answerBatchPreflight([
        ready('a'), conflicting('b'), alreadyThere('c'), ready('d'), alreadyMigrating('e'), conflicting('f'),
      ]);

      expect(text()).toContain('2 file(s) ready to migrate');
      expect(text()).toContain('2 file(s) have a namesake in the target directory');
      expect(text()).toContain('2 file(s) will be left out');
      expect(text()).toContain('c.mp4 — already in the target directory');
      expect(text()).toContain('e.mp4 — already being migrated');
      const conflictList = [...element().querySelectorAll('li')].map(li => li.textContent!.trim());
      expect(conflictList).toEqual(expect.arrayContaining(['b.mp4', 'f.mp4']));
      expect(await checkedStrategy()).toBe('rename');
    });

    it('sends the ready and conflicting files with the chosen strategy, never the left-out ones', async () => {
      /*
        Given the batch preflight check found two ready, two with a namesake and one left out
        When the user picks overwrite and starts the migration
        Then the batch is created for the four ready and conflicting files with the overwrite strategy
      */
      await openBatch(5);
      await answerBatchPreflight([ready('a'), conflicting('b'), alreadyMigrating('c'), ready('d'), conflicting('e')]);

      await pickStrategy('Overwrite');

      expect(await sentInput(CreateMigrationBatchDocument)).toEqual({
        sourceVideoIds: ['a', 'd', 'b', 'e'],
        targetDirRelativePath: { relativePath: 'local/dst' },
        conflictStrategy: 'overwrite',
      });
    });

    it('sends only the ready files when the user skips the conflicting ones', async () => {
      /*
        Given the batch preflight check found two ready and two with a namesake
        When the user picks skip and starts the migration
        Then the batch is created for the two ready files only
      */
      await openBatch(4);
      await answerBatchPreflight([conflicting('a'), ready('b'), conflicting('c'), ready('d')]);

      await pickStrategy('Skip');
      const input = await sentInput(CreateMigrationBatchDocument);

      expect(input.sourceVideoIds).toEqual(['b', 'd']);
    });

    it('sends no strategy when nothing conflicts', async () => {
      /*
        Given the batch preflight check found three ready files and nothing else
        Then no conflict strategy is offered
        When the user starts the migration
        Then the batch is created for the three files without a conflict strategy
      */
      await openBatch(3);
      await answerBatchPreflight([ready('a'), ready('b'), ready('c')]);

      expect(await loader.getAllHarnesses(MatRadioButtonHarness)).toHaveLength(0);
      const input = await sentInput(CreateMigrationBatchDocument);

      expect(input.sourceVideoIds).toEqual(['a', 'b', 'c']);
      expect(input.conflictStrategy).toBeUndefined();
    });

    it('blocks a batch that does not fit or has nothing to send', async () => {
      /*
        Given three videos are moved
        When the batch preflight check reports two ready files but not enough space for them together
        Then "Start Migration" is disabled
        When instead every file is left out
        Then "Start Migration" is disabled
        When instead every file has a namesake and the user picks skip
        Then "Start Migration" is disabled
      */
      await openBatch(3);

      await answerBatchPreflight([ready('a'), ready('b'), alreadyThere('c')], { spaceSufficient: false });
      expect(text()).toContain('Insufficient space');
      expect(await isEnabled('Start Migration')).toBe(false);

      await press('Back');
      await answerBatchPreflight([alreadyThere('a'), alreadyMigrating('b'), alreadyThere('c')]);
      expect(await isEnabled('Start Migration')).toBe(false);

      await press('Back');
      await answerBatchPreflight([conflicting('a'), conflicting('b'), conflicting('c')]);
      expect(await isEnabled('Start Migration')).toBe(true);
      await pickStrategy('Skip');
      expect(await isEnabled('Start Migration')).toBe(false);
    });

    it('reports which files the backend skipped and tracks the batch', async () => {
      /*
        Given the batch preflight check found three ready files
        When the user starts the migration and the backend creates two tasks
          and skips "c.mp4" because it is "already being migrated"
        Then a warning toast says 2 tasks were created and 1 skipped, naming "c.mp4" and the reason
        And the batch is tracked with its two tasks
        And the panel closes reporting success
      */
      await openBatch(3);
      await answerBatchPreflight([ready('a'), ready('b'), ready('c')]);

      const { tasks } = await startAndAnswerBatch({
        batchId: 'batch-1',
        created: 2,
        skipped: [{ sourceVideoId: 'c', reason: 'already being migrated' }],
      });

      expect(toast).toHaveBeenCalledExactlyOnceWith(
        expect.stringMatching(/2 migration tasks created, 1 skipped\. c\.mp4: already being migrated/),
        ToastType.Warning,
      );
      expect(trackBatch).toHaveBeenCalledExactlyOnceWith('batch-1', tasks);
      expect(close).toHaveBeenCalledExactlyOnceWith(true);
    });

    it('stays open when the backend creates no task at all', async () => {
      /*
        Given the batch preflight check found two ready files
        When the user starts the migration and the backend skips both
        Then an error toast says no migration task was created, naming both files and reasons
        And the panel stays open and tracks nothing
      */
      await openBatch(2);
      await answerBatchPreflight([ready('a'), ready('b')]);

      await startAndAnswerBatch({
        batchId: null,
        created: 0,
        skipped: [
          { sourceVideoId: 'a', reason: 'source file does not exist' },
          { sourceVideoId: 'b', reason: 'already being migrated' },
        ],
      });

      expect(toast).toHaveBeenCalledExactlyOnceWith(
        'No migration task was created. a.mp4: source file does not exist; b.mp4: already being migrated',
        ToastType.Error,
      );
      expect(trackBatch).not.toHaveBeenCalled();
      expect(close).not.toHaveBeenCalled();
    });
  });
});
