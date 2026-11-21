import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { Sidebar } from './sidebar';
import { PageStateService } from '../../../services/Page-state-service/page-state.service';
import { environment } from '../../../../environments/environment';

describe('Sidebar', () => {
  let fixture: ComponentFixture<Sidebar>;

  beforeEach(async () => {
    TestBed.configureTestingModule({ providers: [provideRouter([{ path: '**', children: [] }])] });
    fixture = TestBed.createComponent(Sidebar);
    await fixture.whenStable();
  });

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  const links = () => [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>('nav a')];

  it('links to every page', async () => {
    /*
      Given the sidebar is shown
      Then it links to "/home", "/search", "/file-browser" and "/management"
    */
    expect(links().map(a => a.getAttribute('href'))).toEqual(['/home', '/search', '/file-browser', '/management']);
  });

  it('forgets the state this tab kept for the pages when the user navigates', async () => {
    /*
      Given this tab kept the search page state and another tab shared a state
      When the user clicks "Search" in the sidebar
      Then the state this tab kept is gone
      And the shared state is still there
    */
    const states = TestBed.inject(PageStateService);
    states.setState('search', { title: 'cat' }, false);
    states.setState('shared', { title: 'dog' }, true);

    links()[1].click();
    await fixture.whenStable();

    expect(states.getState('search', false)).toBeUndefined();
    expect(states.getState('shared', true)).toEqual({ title: 'dog' });
  });

  it('scrolls the page back to the top', async () => {
    /*
      Given the main container is scrolled down
      When the user clicks the scroll-to-top button
      Then the main container scrolls smoothly to the top
    */
    const main = document.createElement('div');
    main.id = environment.containerIds.rootMainContainerId;
    main.scrollTo = vi.fn();
    document.body.appendChild(main);

    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('aside > div:last-child button')!.click();

    expect(main.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
    main.remove();
  });
});
