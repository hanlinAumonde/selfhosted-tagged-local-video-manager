import { ComponentFixture, DeferBlockBehavior, DeferBlockState, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatCheckboxHarness } from '@angular/material/checkbox/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { provideRouter } from '@angular/router';

import { FileBrowseGrid } from './file-browse-grid';
import { FileBrowseNode, ResultState } from '../../models/GQL-result.model';
import { SortCriterion } from '../../models/management.model';
import { HttpClientService } from '../../../services/Http-client-service/Http-client.service';
import { FakeThumbnails, fakeBlobUrls } from '../../../../testing/thumbnail-fixtures';
import { aBrowseNode } from '../../../../testing/video-fixtures';

const listed = (...nodes: FileBrowseNode[]): ResultState<FileBrowseNode[]> => ({ loading: false, error: null, data: nodes });
const withTags = (...names: string[]) => names.map(name => ({ __typename: 'VideoTag' as const, name }));

describe('FileBrowseGrid', () => {
  let fixture: ComponentFixture<FileBrowseGrid>;
  let loader: HarnessLoader;
  let thumbnails: FakeThumbnails;
  let reported: Record<'nodeClick' | 'selectionToggle' | 'selectAllToggle' | 'sort' | 'refresh', unknown[]>;

  async function showGrid(contents: ResultState<FileBrowseNode[]>, options: { selected?: string[]; sort?: SortCriterion } = {}) {
    fakeBlobUrls();
    thumbnails = new FakeThumbnails();
    TestBed.configureTestingModule({
      imports: [FileBrowseGrid],
      providers: [provideRouter([]), { provide: HttpClientService, useValue: thumbnails }],
      deferBlockBehavior: DeferBlockBehavior.Manual,
    });
    fixture = TestBed.createComponent(FileBrowseGrid);
    fixture.componentRef.setInput('directoryContents', contents);
    fixture.componentRef.setInput('sortCriteria', options.sort ?? { index: 0, order: true });
    fixture.componentRef.setInput('selectedIds', new Set(options.selected ?? []));
    fixture.componentRef.setInput('currentPath', ['local', 'movies']);

    const grid = fixture.componentInstance;
    reported = { nodeClick: [], selectionToggle: [], selectAllToggle: [], sort: [], refresh: [] };
    grid.nodeClick.subscribe(item => reported.nodeClick.push(item.node.name));
    grid.selectionToggle.subscribe(id => reported.selectionToggle.push(id));
    grid.selectAllToggle.subscribe(() => reported.selectAllToggle.push(true));
    grid.sort.subscribe(index => reported.sort.push(index));
    grid.refresh.subscribe(() => reported.refresh.push(true));

    loader = TestbedHarnessEnvironment.loader(fixture);
    await fixture.whenStable();
  }

  async function select(...ids: string[]) {
    fixture.componentRef.setInput('selectedIds', new Set(ids));
    await fixture.whenStable();
  }

  const element = () => fixture.nativeElement as HTMLElement;
  const text = () => element().textContent!.replace(/\s+/g, ' ');
  const tiles = () => [...element().querySelectorAll<HTMLElement>('div.group')];
  const tile = (name: string) => tiles().find(t => t.textContent!.includes(name))!;
  const tooltipOf = (name: string) =>
    fixture.debugElement.queryAll(By.directive(MatTooltip))
      .find(debug => debug.nativeElement === tile(name))!
      .injector.get(MatTooltip).message;

  /** Only video tiles hold a checkbox, in listing order, after the select-all one. */
  async function checkboxOf(name: string) {
    const videoTiles = tiles().filter(t => t.querySelector('mat-checkbox'));
    return (await loader.getAllHarnesses(MatCheckboxHarness))[1 + videoTiles.indexOf(tile(name))];
  }
  const selectAll = async () => (await loader.getAllHarnesses(MatCheckboxHarness))[0];
  const sortButton = (label: string) =>
    [...element().querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent!.includes(label))!;

  it('says when the listing is loading, failed or empty', async () => {
    /*
      Given the listing is loading
      Then the grid says "Loading..."
      Given instead the listing failed
      Then it says "Failed to load directory"
      Given instead the listing is empty
      Then it says "No items in this directory"
    */
    await showGrid({ loading: true, error: null, data: null });
    expect(text()).toContain('Loading...');

    fixture.componentRef.setInput('directoryContents', { loading: false, error: 'boom', data: null });
    await fixture.whenStable();
    expect(text()).toContain('Failed to load directory');

    fixture.componentRef.setInput('directoryContents', listed());
    await fixture.whenStable();
    expect(text()).toContain('No items in this directory');
  });

  it('shows a tile per folder and video, fetching a thumbnail only once a tile is in view', async () => {
    /*
      Given the listing holds folder "clips" and video "trip"
      Then there is a tile for "clips" and for "trip", and only "trip" has a checkbox
      And no thumbnail is fetched yet
      When the tile of "trip" comes into view
      Then the thumbnail of "trip" is fetched
    */
    await showGrid(listed(aBrowseNode({ name: 'clips', isDir: true }), aBrowseNode({ id: 'trip', name: 'trip.mp4' })));

    expect(tiles().map(t => [t.textContent!.trim(), !!t.querySelector('mat-checkbox')])).toEqual([
      ['clips', false],
      ['trip.mp4', true],
    ]);
    expect(thumbnails.requestedIds()).toEqual([]);

    const [deferred] = await fixture.getDeferBlocks();
    await deferred.render(DeferBlockState.Complete);

    expect(thumbnails.requestedIds()).toEqual(['trip']);
  });

  it('describes a tile in its tooltip', async () => {
    /*
      Given video "trip.mp4" by "bob", 1.5 MB, 65 seconds long, tagged "a" and "b"
      And folder "clips" of 0 bytes
      Then the tooltip of "trip.mp4" lists its name, author, size, duration and tags
      And the tooltip of "clips" lists its name and "-" for its size
    */
    await showGrid(listed(
      aBrowseNode({ name: 'trip.mp4', author: 'bob', size: 1.5 * 1024 * 1024, duration: 65, tags: withTags('a', 'b') }),
      aBrowseNode({ name: 'clips', isDir: true, size: 0 }),
    ));

    expect(tooltipOf('trip.mp4')).toBe('Name: trip.mp4\nAuthor: bob\nSize: 1.5 MB\nDuration: 1:05\nTags: a, b');
    expect(tooltipOf('clips')).toBe('Name: clips\nSize: -');
  });

  it('marks which sub-directory a search result came from', async () => {
    /*
      Given the listing is a search result holding video "found.mp4" from "sub/dir"
      Then its tile shows "sub/dir"
    */
    await showGrid(listed(aBrowseNode({ name: 'found.mp4', relativePath: 'sub/dir' })));

    expect(tile('found.mp4').textContent).toContain('sub/dir');
  });

  it('locks a video that a migration is holding', async () => {
    /*
      Given the listing holds video "busy" that a migration is holding
      Then its tile says "Migrating" and its checkbox is disabled
    */
    await showGrid(listed(aBrowseNode({ name: 'busy.mp4', isLocked: true })));

    expect(tile('busy.mp4').textContent).toContain('Migrating');
    expect(await (await checkboxOf('busy.mp4')).isDisabled()).toBe(true);
  });

  it('reports a click on a tile but not on its checkbox', async () => {
    /*
      Given the listing holds folder "clips" and video "trip"
      When the user clicks the tile of "clips"
      Then "clips" is reported as clicked
      When the user ticks the checkbox of "trip"
      Then "trip" is reported for selection and no further tile click is reported
    */
    await showGrid(listed(aBrowseNode({ name: 'clips', isDir: true }), aBrowseNode({ id: 'trip', name: 'trip.mp4' })));

    tile('clips').click();
    await (await checkboxOf('trip.mp4')).toggle();

    expect(reported.nodeClick).toEqual(['clips']);
    expect(reported.selectionToggle).toEqual(['trip']);
  });

  it('ticks select-all once every video that can be selected is selected', async () => {
    /*
      Given the listing holds folder "clips", videos "v1" and "v2" and video "busy" held by a migration
      Then select-all is neither ticked nor partly ticked
      When "v1" is selected
      Then select-all is partly ticked
      When "v1" and "v2" are selected
      Then select-all is ticked
      When the user clicks select-all
      Then select-all is reported
    */
    await showGrid(listed(
      aBrowseNode({ id: 'clips', isDir: true }),
      aBrowseNode({ id: 'v1' }),
      aBrowseNode({ id: 'busy', isLocked: true }),
      aBrowseNode({ id: 'v2' }),
    ));
    const state = async () => {
      const box = await selectAll();
      return { ticked: await box.isChecked(), partly: await box.isIndeterminate() };
    };

    expect(await state()).toEqual({ ticked: false, partly: false });

    await select('v1');
    expect(await state()).toEqual({ ticked: false, partly: true });

    await select('v1', 'v2');
    expect(await state()).toEqual({ ticked: true, partly: false });

    await (await selectAll()).toggle();
    expect(reported.selectAllToggle).toHaveLength(1);
  });

  it('sorts by the picked option and shows its direction', async () => {
    /*
      Given the listing is sorted by size, descending
      Then only "Size" shows a direction, pointing down
      When the user picks "Name", "Size" and "Last update"
      Then sorting by 0, 1 and 2 is reported
      When the user clicks the refresh icon
      Then a refresh is reported
    */
    await showGrid(listed(aBrowseNode()), { sort: { index: 1, order: false } });

    const directions = ['Name', 'Size', 'Last update'].map(l => sortButton(l).querySelector('mat-icon')?.getAttribute('fonticon') ?? null);
    expect(directions).toEqual([null, 'arrow_downward', null]);

    ['Name', 'Size', 'Last update'].forEach(label => sortButton(label).click());
    expect(reported.sort).toEqual([0, 1, 2]);

    element().querySelector<HTMLElement>('mat-icon[fonticon="refresh"]')!.click();
    expect(reported.refresh).toHaveLength(1);
  });
});
