import { ComponentFixture, DeferBlockBehavior, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatCheckboxHarness } from '@angular/material/checkbox/testing';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';

import { FileBrowser } from './file-browser';
import {
  BrowseDirectoryDocument,
  GetDirectoryMetadataDocument,
  SearchInDirectoryDocument,
} from '../../core/graphql/generated/graphql';
import { HttpClientService } from '../../services/Http-client-service/Http-client.service';
import { ToastService } from '../../services/toast-service/toast.service';
import { VideoUpdateEventService } from '../../services/video-update-event-service/video-update-event.service';
import { BottomToolbar } from '../../shared/components/bottom-toolbar/bottom-toolbar';
import { FileBrowseNode } from '../../shared/models/GQL-result.model';
import { ToastType } from '../../shared/models/toast.model';
import { apolloAsInTheApp } from '../../../testing/apollo-testing';
import { FakeThumbnails, fakeBlobUrls } from '../../../testing/thumbnail-fixtures';
import { aBrowseNode } from '../../../testing/video-fixtures';

const tick = () => new Promise<void>(resolve => setTimeout(resolve));
const video = (name: string, overrides: Parameters<typeof aBrowseNode>[0] = {}) => aBrowseNode({ id: name, name, ...overrides });
const directory = (name: string, size = 1024) => aBrowseNode({ id: `dir-${name}`, name, isDir: true, size });

describe('FileBrowser', () => {
  let fixture: ComponentFixture<FileBrowser>;
  let apollo: ApolloTestingController;
  let toast: ReturnType<typeof vi.spyOn>;

  async function openBrowser() {
    fakeBlobUrls();
    TestBed.configureTestingModule({
      imports: [ApolloTestingModule],
      providers: [provideRouter([]), { provide: HttpClientService, useValue: new FakeThumbnails() }],
      // The grid defers its tiles until they scroll into view, which jsdom cannot observe.
      deferBlockBehavior: DeferBlockBehavior.Manual,
    });
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
    fixture = TestBed.createComponent(FileBrowser);
    await settle();
  }

  /** Simulates a reload: a fresh app, with whatever the tab kept in session storage. */
  async function reload() {
    fixture.destroy();
    TestBed.resetTestingModule();
    await openBrowser();
  }

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  async function settle() {
    await tick();
    await fixture.whenStable();
  }

  /** Answers the pending listing; returns what it asked for. */
  async function list(...nodes: FileBrowseNode[]) {
    const op = apollo.expectOne(BrowseDirectoryDocument);
    op.flushData({ browseDirectory: nodes });
    await settle();
    return op.operation.variables['input'];
  }

  const element = () => fixture.nativeElement as HTMLElement;
  const text = () => element().textContent!.replace(/\s+/g, ' ');
  const rows = () => [...element().querySelectorAll<HTMLElement>('tbody tr')];
  const rowNames = () => rows().map(tr => tr.querySelector('td:nth-child(3) span')!.textContent!.trim());
  const row = (name: string) => rows().find(tr => tr.textContent!.includes(name))!;
  const toolbar = () => fixture.debugElement.query(By.directive(BottomToolbar)).componentInstance as BottomToolbar;
  const loader = () => TestbedHarnessEnvironment.loader(fixture);

  async function click(name: string) {
    row(name).click();
    await settle();
  }

  async function tickedCount() {
    const boxes = await loader().getAllHarnesses(MatCheckboxHarness.with({ ancestor: 'tbody' }));
    return (await Promise.all(boxes.map(b => b.isChecked()))).filter(Boolean).length;
  }

  it('lists the root directory, sorted by name', async () => {
    /*
      Given the root holds "b.mp4", "a.mp4" and directory "movies"
      When the file browser opens
      Then the root is listed with sizes worked out recursively
      And the rows read "a.mp4", "b.mp4", "movies"
    */
    await openBrowser();

    const asked = await list(video('b.mp4'), video('a.mp4'), directory('movies'));

    expect(asked).toEqual({ relativePath: undefined, skipCache: false, recursiveCalculation: true });
    expect(rowNames()).toEqual(['a.mp4', 'b.mp4', 'movies']);
  });

  it('opens the directory the user clicks and remembers it across a reload', async () => {
    /*
      Given the root listing holds directory "movies"
      When the user clicks "movies"
      Then "movies" is listed
      When the page is reloaded
      Then "movies" is listed again
    */
    await openBrowser();
    await list(directory('movies'));

    await click('movies');
    expect((await list(video('cat.mp4'))).relativePath).toBe('movies');
    expect(rowNames()).toEqual(['cat.mp4']);

    await reload();
    expect((await list(video('cat.mp4'))).relativePath).toBe('movies');
  });

  it('selects videos by clicking them, and all of them at once', async () => {
    /*
      Given a listing of "a.mp4", "b.mp4" and directory "movies"
      When the user clicks "a.mp4"
      Then 1 video is ticked
      When the user ticks select-all
      Then both videos are ticked
      When the user ticks select-all again
      Then nothing is ticked
    */
    await openBrowser();
    await list(video('a.mp4'), video('b.mp4'), directory('movies'));
    const selectAll = () => loader().getHarness(MatCheckboxHarness.with({ ancestor: 'thead' }));

    await click('a.mp4');
    expect(await tickedCount()).toBe(1);

    await (await selectAll()).toggle();
    await settle();
    expect(await tickedCount()).toBe(2);
    expect(toolbar().selectedCount()).toBe(2);

    await (await selectAll()).toggle();
    await settle();
    expect(await tickedCount()).toBe(0);
  });

  it('refuses to touch a video that is being migrated', async () => {
    /*
      Given a listing holding "busy.mp4", locked by a migration
      When the user clicks "busy.mp4"
      Then a warning toast says it is being migrated
      And nothing is selected
    */
    await openBrowser();
    await list(video('busy.mp4', { isLocked: true }));

    await click('busy.mp4');

    expect(toast).toHaveBeenCalledWith('"busy.mp4" is being migrated and cannot be modified.', ToastType.Warning);
    expect(toolbar().selectedCount()).toBe(0);
  });

  it('searches the current directory and goes back to the listing on exit', async () => {
    /*
      Given the listing of "movies"
      When the toolbar asks for videos named "cat" tagged "pet"
      Then "movies" is searched for them and the results are shown
      When the toolbar exits the search
      Then "movies" is listed afresh
    */
    await openBrowser();
    await list(directory('movies'));
    await click('movies');
    await list(video('a.mp4'));

    toolbar().searchRequested.emit({ name: 'cat', author: '', tags: ['pet'] });
    await settle();
    const search = apollo.expectOne(SearchInDirectoryDocument);
    expect(search.operation.variables['input']).toEqual({
      path: { relativePath: 'movies' }, name: { keyWord: 'cat' }, author: { keyWord: undefined }, tags: ['pet'],
    });
    search.flushData({ searchInDirectory: [video('cat.mp4', { relativePath: 'movies/pets' })] });
    await settle();
    expect(rowNames()).toEqual(['cat.mp4']);
    expect(toolbar().searchSummary()).toEqual(['name: cat', 'tag: pet']);

    toolbar().exitSearch.emit();
    await settle();
    expect(await list(video('a.mp4'))).toEqual({ relativePath: 'movies', skipCache: true, recursiveCalculation: false });
    expect(rowNames()).toEqual(['a.mp4']);
  });

  it('reloads only when a change touches what is on screen', async () => {
    /*
      Given the listing of the root holding "a.mp4" and directory "movies"
      When unrelated video "x" changes elsewhere
      Then nothing is reloaded
      When "a.mp4" changes
      Then the root is listed afresh, without recomputing sizes
      When videos are moved into "movies"
      Then the root is listed afresh
    */
    await openBrowser();
    await list(video('a.mp4'), directory('movies'));
    const events = TestBed.inject(VideoUpdateEventService);

    events.emitUpdated(['x']);
    await settle();
    apollo.expectNone(BrowseDirectoryDocument);

    events.emitUpdated(['a.mp4']);
    await settle();
    expect(await list(video('a.mp4'), directory('movies'))).toEqual({ relativePath: undefined, skipCache: true, recursiveCalculation: false });

    events.emitMigrated('elsewhere', 'movies');
    await settle();
    await list(video('a.mp4'), directory('movies'));
  });

  it('refreshes the metadata of a single directory', async () => {
    /*
      Given the root listing holds directory "movies" of 1 KB
      When its metadata is refreshed and it now holds 5 MB
      Then the "movies" row shows 5 MB
    */
    await openBrowser();
    await list(directory('movies', 1024));
    expect(row('movies').textContent).toContain('1 KB');

    fixture.componentInstance.refreshSelectedDirectory(directory('movies'));
    const op = apollo.expectOne(GetDirectoryMetadataDocument);
    expect(op.operation.variables['input']).toEqual({ relativePath: 'movies' });
    op.flushData({ getDirectoryMetadata: { __typename: 'DirectoryMetadataResult', totalSize: 5 * 1024 * 1024, lastModifiedTime: 0 } });
    await settle();

    expect(row('movies').textContent).toContain('5 MB');
  });

  it('switches to the grid view and remembers it', async () => {
    /*
      Given the file browser shows the table
      When the toolbar toggles the view
      Then the grid is shown and the choice is stored
    */
    await openBrowser();
    await list(video('a.mp4'));
    expect(element().querySelector('app-file-browse-table')).not.toBeNull();

    toolbar().viewModeToggle.emit();
    await settle();

    expect(element().querySelector('app-file-browse-grid')).not.toBeNull();
    expect(element().querySelector('app-file-browse-table')).toBeNull();
    expect(localStorage.getItem('file-browser-view-mode')).toBe('grid');
  });

  it('says when the directory failed to load', async () => {
    /*
      Given loading the root fails with "down"
      Then the table says "Failed to load directory"
      And an error toast names the failure
    */
    await openBrowser();

    apollo.expectOne(BrowseDirectoryDocument).networkError(new Error('down'));
    await settle();

    expect(text()).toContain('Failed to load directory');
    expect(toast).toHaveBeenCalledWith(expect.stringContaining('down'), ToastType.Error);
  });
});
