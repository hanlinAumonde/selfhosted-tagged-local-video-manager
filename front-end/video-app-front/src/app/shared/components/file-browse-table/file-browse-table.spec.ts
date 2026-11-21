import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatCheckboxHarness } from '@angular/material/checkbox/testing';
import { MatMenuItemHarness } from '@angular/material/menu/testing';
import { provideRouter } from '@angular/router';

import { FileBrowseTable } from './file-browse-table';
import { FileBrowseNode, ResultState } from '../../models/GQL-result.model';
import { SortCriterion } from '../../models/management.model';
import { aBrowseNode } from '../../../../testing/video-fixtures';

const listed = (...nodes: FileBrowseNode[]): ResultState<FileBrowseNode[]> => ({ loading: false, error: null, data: nodes });
const withTags = (...names: string[]) => names.map(name => ({ __typename: 'VideoTag' as const, name }));

/** 2023-11-15 at noon UTC: the same calendar day in any time zone the suite may run in. */
const NOV_15_2023 = 1700049600;

describe('FileBrowseTable', () => {
  let fixture: ComponentFixture<FileBrowseTable>;
  let loader: HarnessLoader;
  let reported: Record<'nodeClick' | 'selectionToggle' | 'selectAllToggle' | 'sort' | 'refresh', unknown[]>;

  async function showTable(
    contents: ResultState<FileBrowseNode[]>,
    options: { selected?: string[]; sort?: SortCriterion; visibleTags?: number; path?: string[] } = {},
  ) {
    TestBed.configureTestingModule({ imports: [FileBrowseTable], providers: [provideRouter([])] });
    fixture = TestBed.createComponent(FileBrowseTable);
    fixture.componentRef.setInput('directoryContents', contents);
    fixture.componentRef.setInput('sortCriteria', options.sort ?? { index: 0, order: true });
    fixture.componentRef.setInput('selectedIds', new Set(options.selected ?? []));
    fixture.componentRef.setInput('currentPath', options.path ?? ['local']);
    if (options.visibleTags !== undefined) fixture.componentRef.setInput('visibleTagsCount', options.visibleTags);

    const table = fixture.componentInstance;
    reported = { nodeClick: [], selectionToggle: [], selectAllToggle: [], sort: [], refresh: [] };
    table.nodeClick.subscribe(item => reported.nodeClick.push(item.node.name));
    table.selectionToggle.subscribe(id => reported.selectionToggle.push(id));
    table.selectAllToggle.subscribe(() => reported.selectAllToggle.push(true));
    table.sort.subscribe(index => reported.sort.push(index));
    table.refresh.subscribe(() => reported.refresh.push(true));

    loader = TestbedHarnessEnvironment.loader(fixture);
    await fixture.whenStable();
  }

  async function select(...ids: string[]) {
    fixture.componentRef.setInput('selectedIds', new Set(ids));
    await fixture.whenStable();
  }

  const element = () => fixture.nativeElement as HTMLElement;
  const text = () => element().textContent!.replace(/\s+/g, ' ');
  const row = (name: string) =>
    [...element().querySelectorAll<HTMLElement>('tbody tr')].find(tr => tr.textContent!.includes(name))!;
  const cells = (name: string) => [...row(name).querySelectorAll('td')].map(td => td.textContent!.replace(/\s+/g, ' ').trim());
  const header = (label: string) =>
    [...element().querySelectorAll<HTMLElement>('thead th')].find(th => th.textContent!.includes(label))!;
  const headerIcon = (label: string) => header(label).querySelector('mat-icon')?.getAttribute('fonticon');

  /** Every row holds exactly one checkbox, so a row's position finds its checkbox. */
  async function checkboxOf(name: string) {
    const rowIndex = [...element().querySelectorAll('tbody tr')].indexOf(row(name));
    return (await loader.getAllHarnesses(MatCheckboxHarness.with({ ancestor: 'tbody' })))[rowIndex];
  }
  const selectAll = () => loader.getHarness(MatCheckboxHarness.with({ ancestor: 'thead' }));

  async function openMenuOf(name: string) {
    row(name).querySelector<HTMLButtonElement>('button[mat-icon-button]')!.click();
    await fixture.whenStable();
  }

  it('says when the listing is loading, failed or empty', async () => {
    /*
      Given the listing is loading
      Then the table says "Loading..."
      Given instead the listing failed
      Then it says "Failed to load directory"
      Given instead the listing is empty
      Then it says "No items in this directory"
    */
    await showTable({ loading: true, error: null, data: null });
    expect(text()).toContain('Loading...');

    fixture.componentRef.setInput('directoryContents', { loading: false, error: 'boom', data: null });
    await fixture.whenStable();
    expect(text()).toContain('Failed to load directory');

    fixture.componentRef.setInput('directoryContents', listed());
    await fixture.whenStable();
    expect(text()).toContain('No items in this directory');
  });

  it('lists folders and videos with their details', async () => {
    /*
      Given two tags are shown per video
      And the listing holds folder "clips" and video "trip.mp4" by "bob", 1.5 MB, with tags "a", "b" and "c"
      Then the video row shows its size, date, author, tags "a" and "b" and "+1" for the rest
      And the folder row shows "-" for size, author and tags
    */
    await showTable(listed(
      aBrowseNode({ name: 'clips', isDir: true, size: 0 }),
      aBrowseNode({
        name: 'trip.mp4', author: 'bob', size: 1.5 * 1024 * 1024, lastModifyTime: NOV_15_2023, tags: withTags('a', 'b', 'c'),
      }),
    ), { visibleTags: 2 });

    const [, , name, size, date, author, tags] = cells('trip.mp4');
    expect([name, size, date, author, tags]).toEqual(['trip.mp4', '1.5 MB', '2023/11/15', 'bob', 'a b +1']);

    const [, , folderName, folderSize, , folderAuthor, folderTags] = cells('clips');
    expect([folderName, folderSize, folderAuthor, folderTags]).toEqual(['clips', '-', '-', '-']);
  });

  it('marks which sub-directory a search result came from', async () => {
    /*
      Given the listing is a search result holding video "found.mp4" from "sub/dir"
      Then its row shows "sub/dir"
    */
    await showTable(listed(aBrowseNode({ name: 'found.mp4', relativePath: 'sub/dir' })));

    expect(cells('found.mp4')[2]).toBe('found.mp4 sub/dir');
  });

  it('locks a video that a migration is holding', async () => {
    /*
      Given the listing holds video "busy.mp4" that a migration is holding
      Then its row says "Migrating" and its checkbox is disabled
      When its menu is opened
      Then play, edit, migrate and delete are all disabled
    */
    await showTable(listed(aBrowseNode({ name: 'busy.mp4', isLocked: true })));

    expect(cells('busy.mp4')[2]).toContain('Migrating');
    expect(await (await checkboxOf('busy.mp4')).isDisabled()).toBe(true);

    await openMenuOf('busy.mp4');
    const items = await TestbedHarnessEnvironment.documentRootLoader(fixture).getAllHarnesses(MatMenuItemHarness);
    const states = await Promise.all(items.map(async item => [await item.getText(), await item.isDisabled()]));
    expect(states).toEqual([
      ['Play Video', true],
      ['Edit', true],
      ['Migrate', true],
      ['Delete', true],
    ]);
  });

  it('reports a click on a row but not on its checkbox or menu button', async () => {
    /*
      Given the listing holds folder "clips" and video "trip.mp4"
      When the user clicks the "clips" row
      Then "clips" is reported as clicked
      When the user ticks the checkbox of "trip.mp4"
      Then "trip.mp4" is reported for selection and no row click is reported
      When the user opens the menu of "trip.mp4"
      Then no row click is reported
    */
    await showTable(listed(aBrowseNode({ name: 'clips', isDir: true }), aBrowseNode({ id: 'trip', name: 'trip.mp4' })));

    row('clips').click();
    expect(reported.nodeClick).toEqual(['clips']);

    await (await checkboxOf('trip.mp4')).toggle();
    expect(reported.selectionToggle).toEqual(['trip']);

    await openMenuOf('trip.mp4');
    expect(reported.nodeClick).toEqual(['clips']);
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
    await showTable(listed(
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

  it('sorts by the clicked column and shows its direction', async () => {
    /*
      Given the listing is sorted by size, descending
      Then the size column shows a down arrow and the name and date columns show no direction
      When the user clicks the name, size and date headers
      Then sorting by columns 0, 1 and 2 is reported
      When the user clicks the author header
      Then no sorting is reported
    */
    await showTable(listed(aBrowseNode()), { sort: { index: 1, order: false } });

    expect(['Name', 'Size', 'Last update'].map(headerIcon)).toEqual(['unfold_more', 'arrow_downward', 'unfold_more']);

    ['Name', 'Size', 'Last update', 'Author'].forEach(label => header(label).click());
    expect(reported.sort).toEqual([0, 1, 2]);
  });

  it('asks for a refresh', async () => {
    /*
      Given a listing is shown
      When the user clicks the refresh icon
      Then a refresh is reported
    */
    await showTable(listed(aBrowseNode()));

    element().querySelector<HTMLElement>('thead mat-icon[fonticon="refresh"]')!.click();

    expect(reported.refresh).toHaveLength(1);
  });
});
