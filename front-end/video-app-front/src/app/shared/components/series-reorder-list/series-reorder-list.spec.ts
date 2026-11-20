import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatButtonHarness } from '@angular/material/button/testing';

import { SeriesReorderList } from './series-reorder-list';
import { BatchPanelVideoItem } from '../../models/panels.model';

const items = (...names: string[]): BatchPanelVideoItem[] => names.map(name => ({ id: name, name }));

describe('SeriesReorderList', () => {
  let fixture: ComponentFixture<SeriesReorderList>;
  let reported: string[][];

  async function showList(list: BatchPanelVideoItem[], options: { movableId?: string; emptyHint?: string } = {}) {
    fixture = TestBed.createComponent(SeriesReorderList);
    fixture.componentRef.setInput('items', list);
    if (options.movableId) fixture.componentRef.setInput('movableId', options.movableId);
    if (options.emptyHint) fixture.componentRef.setInput('emptyHint', options.emptyHint);
    reported = [];
    fixture.componentInstance.itemsChange.subscribe(next => reported.push(next.map(item => item.name)));
    await fixture.whenStable();
  }

  const rows = () =>
    [...(fixture.nativeElement as HTMLElement).querySelectorAll('li')].map(li =>
      li.textContent!.replace(/arrow_(upward|downward)/g, '').replace(/\s+/g, ' ').trim(),
    );

  /** Each row holds a "Move up" then a "Move down" button. */
  async function arrows(direction: 'Move up' | 'Move down') {
    return TestbedHarnessEnvironment.loader(fixture).getAllHarnesses(
      MatButtonHarness.with({ selector: `[aria-label="${direction}"]` }),
    );
  }
  const enabled = async (direction: 'Move up' | 'Move down') =>
    Promise.all((await arrows(direction)).map(async b => !(await b.isDisabled())));

  it('numbers the videos in order', async () => {
    /*
      Given the list holds "a", "b" and "c"
      Then it shows "1. a", "2. b" and "3. c"
    */
    await showList(items('a', 'b', 'c'));

    expect(rows()).toEqual(['1. a', '2. b', '3. c']);
  });

  it('says so when there is nothing to order', async () => {
    /*
      Given the list is empty and the hint is "Pick some videos"
      Then it shows "Pick some videos"
    */
    await showList([], { emptyHint: 'Pick some videos' });

    expect((fixture.nativeElement as HTMLElement).textContent!.trim()).toBe('Pick some videos');
  });

  it('moves any video up or down when every video is movable', async () => {
    /*
      Given the list holds "a", "b" and "c" and no video is singled out
      Then "a" cannot move up and "c" cannot move down
      When the user moves "b" up
      Then the order "b", "a", "c" is reported
      When the user moves "b" down
      Then the order "a", "c", "b" is reported
    */
    await showList(items('a', 'b', 'c'));
    expect(await enabled('Move up')).toEqual([false, true, true]);
    expect(await enabled('Move down')).toEqual([true, true, false]);

    await (await arrows('Move up'))[1].click();
    await (await arrows('Move down'))[1].click();

    expect(reported).toEqual([
      ['b', 'a', 'c'],
      ['a', 'c', 'b'],
    ]);
  });

  it('moves only the current video when one is singled out', async () => {
    /*
      Given the list holds "a", "b" and "c" and "b" is the current video
      Then "b" is shown as "Current Video"
      And only "b" can move up or down
    */
    await showList(items('a', 'b', 'c'), { movableId: 'b' });

    expect(rows()).toEqual(['1. a', '2. Current Video', '3. c']);
    expect(await enabled('Move up')).toEqual([false, true, false]);
    expect(await enabled('Move down')).toEqual([false, true, false]);
  });
});
