import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatMenuHarness } from '@angular/material/menu/testing';
import { MatDialog } from '@angular/material/dialog';
import { Subject } from 'rxjs';

import { BottomToolbar } from './bottom-toolbar';
import { PathHistoryService } from '../../../services/path-history-service/path-history.service';
import { ToastService } from '../../../services/toast-service/toast.service';
import { ToastType } from '../../models/toast.model';
import { BatchPanelVideoItem, DeleteType } from '../../models/panels.model';
import { NewFolderPanel } from '../new-folder-panel/new-folder-panel';
import { SearchPanel } from '../search-panel/search-panel';
import { BatchOperationPanel } from '../batch-operation-panel/batch-operation-panel';
import { MigrationPanel } from '../migration-panel/migration-panel';
import { DeleteCheckPanel } from '../delete-check-panel/delete-check-panel';

interface ToolbarState {
  path?: string[];
  selected?: BatchPanelVideoItem[];
  searching?: string[];
}

describe('BottomToolbar', () => {
  let fixture: ComponentFixture<BottomToolbar>;
  let loader: HarnessLoader;
  let dialog: { open: ReturnType<typeof vi.fn> };
  let closed: Subject<unknown>;
  let reported: Record<
    'navigateToPath' | 'createFolderResult' | 'searchRequested' | 'batchOperationResult' | 'migrationResult' | 'exitSearch' | 'viewModeToggle',
    unknown[]
  >;

  async function showToolbar(state: ToolbarState = {}) {
    closed = new Subject();
    dialog = { open: vi.fn(() => ({ afterClosed: () => closed })) };
    TestBed.configureTestingModule({ providers: [{ provide: MatDialog, useValue: dialog }] });
    fixture = TestBed.createComponent(BottomToolbar);
    const toolbar = fixture.componentInstance;
    reported = {
      navigateToPath: [], createFolderResult: [], searchRequested: [], batchOperationResult: [],
      migrationResult: [], exitSearch: [], viewModeToggle: [],
    };
    for (const name of Object.keys(reported) as (keyof typeof reported)[]) {
      (toolbar[name] as { subscribe(fn: (value: unknown) => void): void }).subscribe(value => reported[name].push(value ?? true));
    }
    await update(state);
    loader = TestbedHarnessEnvironment.documentRootLoader(fixture);
  }

  async function update({ path = ['local', 'movies'], selected = [], searching }: ToolbarState) {
    const ref = fixture.componentRef;
    ref.setInput('currentPath', path);
    ref.setInput('isAtRoot', path.length === 0);
    ref.setInput('selectedVideoItems', selected);
    ref.setInput('selectedIds', new Set(selected.map(item => item.id)));
    ref.setInput('selectedCount', selected.length);
    ref.setInput('hasSelection', selected.length > 0);
    ref.setInput('tableWidth', 800);
    ref.setInput('isSearching', !!searching);
    ref.setInput('searchSummary', searching ?? []);
    await fixture.whenStable();
  }

  const element = () => fixture.nativeElement as HTMLElement;
  const shownPath = () => [...element().querySelectorAll('.path-item')].map(item => item.textContent!.trim());
  const pathItem = (name: string) =>
    [...element().querySelectorAll<HTMLElement>('.path-item')].find(item => item.textContent!.trim() === name)!;
  const iconButton = (icon: string) =>
    TestbedHarnessEnvironment.loader(fixture).getHarness(MatButtonHarness.with({ selector: `:has(> mat-icon[fonticon="${icon}"])` }));
  const options = () => loader.getHarness(MatMenuHarness.with({ triggerText: /Options/ }));

  async function optionStates() {
    const menu = await options();
    await menu.open();
    const items = await menu.getItems();
    const states = await Promise.all(items.map(async item => [await item.getText(), !(await item.isDisabled())]));
    await menu.close();
    return Object.fromEntries(states);
  }

  async function pick(...texts: string[]) {
    const [first, ...rest] = texts;
    await (await options()).clickItem({ text: first }, ...rest.map(text => ({ text })));
    await fixture.whenStable();
  }

  const opened = () => {
    const [component, config] = dialog.open.mock.lastCall!;
    return { component, ...config };
  };

  async function close(result: unknown) {
    closed.next(result);
    closed.complete();
    closed = new Subject();
    await fixture.whenStable();
  }

  const selection = [
    { id: 'v1', name: 'one.mp4', size: 10 },
    { id: 'v2', name: 'two.mp4' },
  ];

  describe('the path', () => {
    it('shows where the user is and goes up to any part of it', async () => {
      /*
        Given the user is in "local/movies/2024"
        Then the path reads "Root", "local", "movies", "2024"
        When the user clicks "movies"
        Then going to "local/movies" is asked for and remembered in the history
        When the user clicks "Root"
        Then going to the root is asked for
        When the user clicks "2024", the directory they are in
        Then nothing is asked for
      */
      await showToolbar({ path: ['local', 'movies', '2024'] });
      expect(shownPath()).toEqual(['Root', 'local', 'movies', '2024']);

      const history = TestBed.inject(PathHistoryService);
      pathItem('movies').click();
      expect(history.hasHistory()).toBe(true);
      pathItem('Root').click();
      pathItem('2024').click();

      expect(reported.navigateToPath).toEqual([['local', 'movies'], []]);
    });

    it('folds the start of a path too long to fit into a menu', async () => {
      /*
        Given the path only has room for two of its parts
        When the user is in "local/movies/2024"
        Then the path shows "movies" and "2024", with "Root" and "local" folded away
        When the user opens the fold and picks "local"
        Then going to "local" is asked for
      */
      // jsdom lays nothing out: give each part 100px, each separator 10px and the path 300px.
      const offsetWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth')!;
      const clientWidth = Object.getOwnPropertyDescriptor(Element.prototype, 'clientWidth')!;
      Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
        configurable: true,
        get(this: HTMLElement) {
          return this.classList.contains('path-item') ? 100 : this.classList.contains('path-sep') ? 10 : 0;
        },
      });
      Object.defineProperty(Element.prototype, 'clientWidth', { configurable: true, get: () => 300 });
      try {
        await showToolbar({ path: ['local', 'movies', '2024'] });
        await fixture.whenStable();

        expect(shownPath()).toEqual(['movies', '2024']);

        const fold = await loader.getHarness(MatMenuHarness.with({ selector: ':has(> mat-icon[fonticon="keyboard_double_arrow_left"])' }));
        await fold.open();
        expect(await Promise.all((await fold.getItems()).map(item => item.getText()))).toEqual(['Root', 'local']);
        await fold.clickItem({ text: 'local' });

        expect(reported.navigateToPath).toEqual([['local']]);
      } finally {
        Object.defineProperty(HTMLElement.prototype, 'offsetWidth', offsetWidth);
        Object.defineProperty(Element.prototype, 'clientWidth', clientWidth);
      }
    });

    it('goes back and forward through the history', async () => {
      /*
        Given the user went from the root to "local" and then to "local/movies"
        Then back is enabled and forward is not
        When the user clicks back
        Then going to "local" is asked for, and forward becomes enabled
        When the user clicks forward
        Then going to "local/movies" is asked for
      */
      // The history is not a signal: the toolbar re-reads it when the page hands it the new path.
      await showToolbar({ path: [] });
      const history = TestBed.inject(PathHistoryService);
      history.pushNewPath(['local']);
      history.pushNewPath(['local', 'movies']);
      await update({ path: ['local', 'movies'] });
      const back = await iconButton('arrow_back');
      const forward = await iconButton('arrow_forward');
      expect([await back.isDisabled(), await forward.isDisabled()]).toEqual([false, true]);

      await back.click();
      await update({ path: ['local'] });
      expect(await forward.isDisabled()).toBe(false);
      await forward.click();

      expect(reported.navigateToPath).toEqual([['local'], ['local', 'movies']]);
    });

    it('shows what was searched for instead of the path while searching', async () => {
      /*
        Given the user is searching for name "cat" and tag "pets"
        Then the toolbar shows "cat" and "pets" and no path
        When the user clicks "Back to browsing"
        Then leaving the search is asked for
      */
      await showToolbar({ searching: ['cat', 'pets'] });

      expect(shownPath()).toEqual([]);
      expect(element().textContent).toContain('cat');
      expect(element().textContent).toContain('pets');

      await (await iconButton('keyboard_return')).click();
      expect(reported.exitSearch).toHaveLength(1);
    });
  });

  describe('the options', () => {
    it('offers search and a new folder only inside a resource directory', async () => {
      /*
        Given the user is in the category "local"
        Then "Search" and "New folder" are disabled
        Given instead the user is in "local/movies"
        Then both are enabled
      */
      await showToolbar({ path: ['local'] });
      expect(await optionStates()).toMatchObject({ Search: false, 'New folder': false });

      await update({ path: ['local', 'movies'] });
      expect(await optionStates()).toMatchObject({ Search: true, 'New folder': true });
    });

    it('creates a folder in the current directory and reports the outcome', async () => {
      /*
        Given the user is in "local/movies" and a toast is showing
        When the user picks "New folder"
        Then the toasts are cleared and the new folder panel opens for "local/movies"
        When the panel closes having created the folder
        Then a created folder is reported
      */
      await showToolbar();
      const toasts = TestBed.inject(ToastService);
      toasts.emitNewToast('old news', ToastType.Error);

      await pick('New folder');

      expect(toasts.toasts()).toEqual([]);
      expect(opened()).toMatchObject({ component: NewFolderPanel, data: { parentPath: 'local/movies' } });
      await close(true);
      expect(reported.createFolderResult).toEqual([true]);
    });

    it('searches the current directory with the criteria the panel hands back', async () => {
      /*
        Given the user is in "local/movies"
        When the user picks "Search"
        Then the search panel opens for "local/movies"
        When the panel is dismissed
        Then no search is asked for
        When the user searches again and the panel hands back name "cat"
        Then a search for name "cat" is asked for
      */
      await showToolbar();

      await pick('Search');
      expect(opened()).toMatchObject({ component: SearchPanel, data: { directoryPath: 'local/movies' } });
      await close(undefined);
      expect(reported.searchRequested).toEqual([]);

      await pick('Search');
      const criteria = { name: 'cat', author: '', tags: [] };
      await close(criteria);
      expect(reported.searchRequested).toEqual([criteria]);
    });

    it('offers batch operations only while videos are selected', async () => {
      /*
        Given nothing is selected
        Then "Batch (0)" is disabled
        Given instead 2 videos are selected
        Then "Batch (2)" is enabled
      */
      await showToolbar();
      expect(await optionStates()).toMatchObject({ 'Batch (0)': false });

      await update({ selected: selection });
      expect(await optionStates()).toMatchObject({ 'Batch (2)': true });
    });

    it('edits the selected videos and reports the outcome', async () => {
      /*
        Given videos "v1" and "v2" are selected in "local/movies"
        When the user picks Batch, then "Edit"
        Then the batch panel opens on "v1" and "v2", and cannot be dismissed by clicking outside
        When the panel closes having saved
        Then a batch operation is reported
      */
      await showToolbar({ selected: selection });

      await pick('Batch (2)', 'Edit');

      expect(opened()).toMatchObject({
        component: BatchOperationPanel,
        data: { mode: 'videos', videos: new Set(['v1', 'v2']), videoItems: selection },
        disableClose: true,
      });
      await close(true);
      expect(reported.batchOperationResult).toEqual([true]);
    });

    it('migrates the selected videos from the current directory and reports the outcome', async () => {
      /*
        Given videos "v1" (10 bytes) and "v2" (of unknown size) are selected in "local/movies"
        When the user picks Batch, then "Migrate"
        Then the migration panel opens on "v1" with 10 bytes and "v2" with 0, from "local/movies"
        When the panel is dismissed
        Then a migration that did not start is reported
      */
      await showToolbar({ selected: selection });

      await pick('Batch (2)', 'Migrate');

      expect(opened()).toMatchObject({
        component: MigrationPanel,
        data: {
          videos: [{ id: 'v1', name: 'one.mp4', size: 10 }, { id: 'v2', name: 'two.mp4', size: 0 }],
          sourceCurrentDir: 'local/movies',
        },
      });
      await close(undefined);
      expect(reported.migrationResult).toEqual([false]);
    });

    it('asks to delete the selected videos', async () => {
      /*
        Given videos "v1" and "v2" are selected in "local/movies"
        When the user picks Batch, then "Delete"
        Then the delete panel opens for the 2 videos in "local/movies"
      */
      await showToolbar({ selected: selection });

      await pick('Batch (2)', 'Delete');

      expect(opened()).toMatchObject({
        component: DeleteCheckPanel,
        data: { deleteType: DeleteType.Batch, videoCount: 2, videoIds: new Set(['v1', 'v2']), directoryPath: 'local/movies' },
      });
    });

    it('switches between the list and the thumbnail view', async () => {
      /*
        Given the list view is on
        Then the switch offers the thumbnail view
        When the user clicks it
        Then switching the view is asked for
      */
      await showToolbar();
      const toggle = element().querySelector<HTMLButtonElement>('button:has(> mat-icon[fonticon="grid_view"])');
      expect(toggle).not.toBeNull();

      toggle!.click();
      expect(reported.viewModeToggle).toHaveLength(1);
    });

    it('folds away and back', async () => {
      /*
        Given the toolbar is open
        When the user clicks its handle
        Then the toolbar is folded away
        When the user clicks its handle again
        Then it is open again
      */
      await showToolbar();
      const handle = element().querySelector<HTMLElement>('.rounded-t-lg')!;
      const content = () => element().querySelector<HTMLElement>('.overflow-hidden')!.style.maxHeight;
      expect(content()).toBe('160px');

      handle.click();
      await fixture.whenStable();
      expect(content()).toBe('0px');

      handle.click();
      await fixture.whenStable();
      expect(content()).toBe('160px');
    });
  });
});
