import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatButtonHarness } from '@angular/material/button/testing';

import { Pagination } from './pagination';

describe('Pagination', () => {
  let fixture: ComponentFixture<Pagination>;
  let asked: number[];

  async function showPages(totalPages: number, currentPage: number, isActive = true) {
    fixture = TestBed.createComponent(Pagination);
    fixture.componentRef.setInput('totalPages', totalPages);
    fixture.componentRef.setInput('currentPage', currentPage);
    fixture.componentRef.setInput('isActive', isActive);
    asked = [];
    fixture.componentInstance.pageChanged.subscribe(page => asked.push(page));
    await fixture.whenStable();
  }

  async function moveTo(currentPage: number) {
    fixture.componentRef.setInput('currentPage', currentPage);
    await fixture.whenStable();
  }

  const loader = () => TestbedHarnessEnvironment.loader(fixture);
  const button = (label: string) => loader().getHarness(MatButtonHarness.with({ selector: `[aria-label="${label}"]` }));
  const pageButton = (page: number) => loader().getHarness(MatButtonHarness.with({ text: String(page) }));
  const offeredPages = async () =>
    Promise.all((await loader().getAllHarnesses(MatButtonHarness.with({ selector: '[matButton]' }))).map(b => b.getText()));
  const edgeStates = async () =>
    Promise.all(['First page', 'Previous page', 'Next page', 'Last page'].map(async l => (await button(l)).isDisabled()));

  it('shows a window of five pages around the current one', async () => {
    /*
      Given there are 9 pages
      When the current page is 1
      Then pages 1 to 5 are offered
      When the current page is 5
      Then pages 3 to 7 are offered
      When the current page is 9
      Then pages 5 to 9 are offered
      Given instead there are 3 pages
      Then pages 1 to 3 are offered
    */
    await showPages(9, 1);
    expect(await offeredPages()).toEqual(['1', '2', '3', '4', '5']);

    await moveTo(5);
    expect(await offeredPages()).toEqual(['3', '4', '5', '6', '7']);

    await moveTo(9);
    expect(await offeredPages()).toEqual(['5', '6', '7', '8', '9']);

    await showPages(3, 1);
    expect(await offeredPages()).toEqual(['1', '2', '3']);
  });

  it('asks for the page the user picks', async () => {
    /*
      Given there are 9 pages and the current page is 5
      Then page 5 cannot be picked
      When the user clicks page 6, previous, next, first and last
      Then pages 6, 4, 6, 1 and 9 are asked for
    */
    await showPages(9, 5);
    expect(await (await pageButton(5)).isDisabled()).toBe(true);

    await (await pageButton(6)).click();
    for (const label of ['Previous page', 'Next page', 'First page', 'Last page']) {
      await (await button(label)).click();
    }

    expect(asked).toEqual([6, 4, 6, 1, 9]);
  });

  it('cannot go before the first page or past the last one', async () => {
    /*
      Given there are 9 pages and the current page is 1
      Then first and previous are disabled and next and last are not
      Given instead the current page is 9
      Then next and last are disabled and first and previous are not
    */
    await showPages(9, 1);
    expect(await edgeStates()).toEqual([true, true, false, false]);

    await moveTo(9);
    expect(await edgeStates()).toEqual([false, false, true, true]);
  });

  it('shows a disabled placeholder while inactive', async () => {
    /*
      Given the pagination is inactive
      Then every button is disabled and no page number is shown
    */
    await showPages(9, 1, false);

    const buttons = await loader().getAllHarnesses(MatButtonHarness);
    expect(await Promise.all(buttons.map(b => b.isDisabled()))).not.toContain(false);
    expect((fixture.nativeElement as HTMLElement).textContent).not.toMatch(/\d/);
  });
});
