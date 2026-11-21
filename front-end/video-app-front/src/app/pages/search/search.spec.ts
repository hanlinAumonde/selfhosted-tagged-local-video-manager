import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatDialog } from '@angular/material/dialog';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';
import { Subject } from 'rxjs';

import { Search } from './search';
import { SearchFrom, SearchVideosDocument, VideoSortOption } from '../../core/graphql/generated/graphql';
import { HttpClientService } from '../../services/Http-client-service/Http-client.service';
import { PageStateService } from '../../services/Page-state-service/page-state.service';
import { VideoUpdateEventService } from '../../services/video-update-event-service/video-update-event.service';
import { SearchedVideo } from '../../shared/models/GQL-result.model';
import { SearchPageParam } from '../../shared/models/search.model';
import { VideoEditPanel } from '../../shared/components/video-edit-panel/video-edit-panel';
import { apolloAsInTheApp } from '../../../testing/apollo-testing';
import { FakeThumbnails, fakeBlobUrls } from '../../../testing/thumbnail-fixtures';
import { aSearchedVideo } from '../../../testing/video-fixtures';

const tick = (ms = 0) => new Promise<void>(resolve => setTimeout(resolve, ms));
/** The page waits this long before it runs a search. */
const SEARCH_DEBOUNCE = 300;

describe('Search', () => {
  let harness: RouterTestingHarness;
  let apollo: ApolloTestingController;
  let dialog: { open: ReturnType<typeof vi.fn> };
  let closed: Subject<unknown>;

  async function openSearch(options: { page?: number; state?: SearchPageParam; handedOver?: SearchPageParam } = {}) {
    fakeBlobUrls();
    closed = new Subject();
    dialog = { open: vi.fn(() => ({ afterClosed: () => closed })) };
    TestBed.configureTestingModule({
      imports: [ApolloTestingModule],
      providers: [
        provideRouter([{ path: 'search', component: Search }]),
        { provide: HttpClientService, useValue: new FakeThumbnails() },
        { provide: MatDialog, useValue: dialog },
      ],
    });
    apollo = apolloAsInTheApp();
    if (options.handedOver) TestBed.inject(PageStateService).setState('/search', options.handedOver, true);
    harness = await RouterTestingHarness.create();
    await TestBed.inject(Router).navigate(['/search'], {
      queryParams: options.page ? { currentPageNumber: options.page } : {},
      state: options.state,
    });
    await settle();
  }

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  async function settle(ms = 0) {
    await tick(ms);
    await harness.fixture.whenStable();
  }

  /** Lets the pending search go out and answers it; returns what it asked for. */
  async function answer(videos: SearchedVideo[], { totalCount = videos.length, size = 10 } = {}) {
    await settle(SEARCH_DEBOUNCE + 50);
    const op = apollo.match(SearchVideosDocument).at(-1);
    expect(op, 'a search was sent').toBeDefined();
    op!.flushData({
      SearchVideos: {
        __typename: 'VideoSearchResult',
        pagination: { __typename: 'Pagination', size, totalCount, currentPageNumber: 1 },
        videos,
      },
    });
    await settle();
    return op!.operation.variables['input'];
  }

  async function searchedNothing() {
    await settle(SEARCH_DEBOUNCE + 50);
    return apollo.match(SearchVideosDocument).length === 0;
  }

  const page = () => harness.routeNativeElement!;
  const text = () => page().textContent!.replace(/\s+/g, ' ');
  const url = () => TestBed.inject(Router).url;
  const fields = () => [...page().querySelectorAll<HTMLInputElement>('input[type="text"]')];
  const cards = () => [...page().querySelectorAll('app-video-card p.font-semibold')].map(p => p.textContent!.trim());
  const searchButton = () => page().querySelector<HTMLButtonElement>('button:has(> mat-icon[fonticon="search"])')!;
  const loader = () => TestbedHarnessEnvironment.loader(harness.fixture);

  async function type(field: HTMLInputElement, value: string) {
    field.value = value;
    field.dispatchEvent(new Event('input'));
    await settle();
  }

  async function sortBy(option: VideoSortOption) {
    const select = page().querySelector('select')!;
    select.value = option;
    select.dispatchEvent(new Event('change'));
    await settle();
  }

  /** Opens page `n` of a search whose results are already on screen. */
  async function showPage(n: number, of: number) {
    await TestBed.inject(Router).navigate(['/search'], { queryParams: { currentPageNumber: n } });
    await answer([aSearchedVideo()], { totalCount: of * 10 });
  }

  it('waits for the user to search', async () => {
    /*
      Given the search page is opened with nothing handed to it
      Then no results area is shown and nothing is searched
    */
    await openSearch();

    expect(page().querySelector('.animate-fade-in')).toBeNull();
    expect(await searchedNothing()).toBe(true);
  });

  it('searches the typed title and creator from the first page', async () => {
    /*
      Given the search page is opened
      When the user types title "cat" and creator "bob" and clicks search
      Then page 1 is opened and videos titled "cat" by "bob" are searched, latest viewed first
      When 25 videos match, 10 per page, and the first page holds "a" and "b"
      Then "a" and "b" are shown with 3 pages to pick from
    */
    await openSearch();
    const [title, creator] = fields();
    await type(title, 'cat');
    await type(creator, 'bob');

    searchButton().click();
    await settle();

    expect(url()).toBe('/search?currentPageNumber=1');
    const sent = await answer([aSearchedVideo({ name: 'a' }), aSearchedVideo({ name: 'b' })], { totalCount: 25 });
    expect(sent).toEqual({
      titleKeyword: { keyWord: 'cat' },
      author: { keyWord: 'bob' },
      currentPageNumber: 1,
      sortBy: VideoSortOption.Latest,
      fromPage: SearchFrom.SearchPage,
      tags: [],
    });
    expect(cards()).toEqual(['a', 'b']);
    const pageNumbers = await loader().getAllHarnesses(MatButtonHarness.with({ selector: 'app-pagination [matButton]' }));
    expect(await Promise.all(pageNumbers.map(b => b.getText()))).toEqual(['1', '2', '3']);
  });

  it('goes to the page the user picks', async () => {
    /*
      Given a search showing page 1 of 3
      When the user picks page 2
      Then page 2 is opened and searched for
    */
    await openSearch({ page: 1 });
    await answer([aSearchedVideo()], { totalCount: 30 });

    await (await loader().getHarness(MatButtonHarness.with({ text: '2' }))).click();
    await settle();

    expect(url()).toBe('/search?currentPageNumber=2');
    expect((await answer([aSearchedVideo()], { totalCount: 30 })).currentPageNumber).toBe(2);
  });

  it('runs the search handed over by the page that opened it', async () => {
    /*
      Given the home page opened the search page on page 1, sorted by most viewed
      Then the most viewed videos are searched right away
      Given instead another tab handed over the tag "cats"
      Then videos tagged "cats" are searched right away
    */
    await openSearch({ page: 1, state: { sortBy: VideoSortOption.MostViewed } });
    expect(await answer([])).toMatchObject({ sortBy: VideoSortOption.MostViewed, currentPageNumber: 1 });

    TestBed.resetTestingModule();
    await openSearch({ page: 1, handedOver: { tags: ['cats'] } });
    expect(await answer([])).toMatchObject({ tags: ['cats'] });
  });

  it('refuses a title that is too long', async () => {
    /*
      Given the user types a 201-character title
      Then the search button is disabled
      And pressing Enter searches nothing
    */
    await openSearch();

    await type(fields()[0], 'x'.repeat(201));
    expect(searchButton().disabled).toBe(true);

    fields()[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
    expect(await searchedNothing()).toBe(true);
  });

  it('filters by the tags picked in the tag filter', async () => {
    /*
      Given a search tagged "old" showing page 2
      When the user opens the tag filter
      Then it opens in filter mode with "old" picked
      When the user dismisses it
      Then nothing changes
      When the user opens it again and picks "cats" and "dogs"
      Then the badge reads 2 and videos tagged "cats" and "dogs" are searched from page 1
    */
    await openSearch({ page: 2, state: { tags: ['old'] } });
    await answer([aSearchedVideo()], { totalCount: 30 });
    const tagFilter = () => [...page().querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent!.includes('Tag filter'))!;

    tagFilter().click();
    expect(dialog.open).toHaveBeenLastCalledWith(VideoEditPanel, expect.objectContaining({ data: { mode: 'filter', selectedTags: ['old'] } }));
    closed.next(undefined);
    await settle();
    expect(url()).toBe('/search?currentPageNumber=2');
    expect(await searchedNothing()).toBe(true);

    closed = new Subject();
    tagFilter().click();
    closed.next(['cats', 'dogs']);
    await settle();

    expect(tagFilter().textContent).toContain('2');
    expect(url()).toBe('/search?currentPageNumber=1');
    expect(await answer([])).toMatchObject({ tags: ['cats', 'dogs'], currentPageNumber: 1 });
  });

  it('sorts the results, back to the first page when the sort can change how many match', async () => {
    /*
      Given a search showing page 2
      When the user sorts by most viewed
      Then most viewed is searched, still on page 2
      When the user sorts by loved
      Then loved is searched from page 1
    */
    await openSearch({ page: 2, state: { title: 'cat' } });
    await answer([aSearchedVideo()], { totalCount: 30 });

    await sortBy(VideoSortOption.MostViewed);
    expect(url()).toBe('/search?currentPageNumber=2');
    expect(await answer([aSearchedVideo()], { totalCount: 30 })).toMatchObject({ sortBy: VideoSortOption.MostViewed, currentPageNumber: 2 });

    await sortBy(VideoSortOption.Loved);
    expect(url()).toBe('/search?currentPageNumber=1');
    expect(await answer([])).toMatchObject({ sortBy: VideoSortOption.Loved, currentPageNumber: 1 });
  });

  it('says when nothing matched or the search failed', async () => {
    /*
      Given a search that matches nothing
      Then it says "No videos found"
      Given instead a search that fails
      Then it says "Failed to load search results"
    */
    await openSearch({ page: 1 });
    await answer([]);
    expect(text()).toContain('No videos found');

    await sortBy(VideoSortOption.Longest);
    await settle(SEARCH_DEBOUNCE + 50);
    apollo.match(SearchVideosDocument).at(-1)!.networkError(new Error('down'));
    await settle();
    expect(text()).toContain('Failed to load search results');
  });

  it('clears a field with its close button', async () => {
    /*
      Given the user typed title "cat"
      When the user clicks the close button of the title
      Then the title is empty
    */
    await openSearch();
    await type(fields()[0], 'cat');

    page().querySelector<HTMLButtonElement>('button:has(> mat-icon[fonticon="close"])')!.click();
    await settle();

    expect(fields()[0].value).toBe('');
  });

  it('searches again when any video changes, since what matches may have changed', async () => {
    /*
      Given a search sorted by loved, holding "a"
      When another video "x" is loved elsewhere
      Then the search runs again
    */
    await openSearch({ page: 1, state: { sortBy: VideoSortOption.Loved } });
    await answer([aSearchedVideo({ id: 'a' })]);

    TestBed.inject(VideoUpdateEventService).emitUpdated(['x']);

    expect(await answer([aSearchedVideo({ id: 'a' }), aSearchedVideo({ id: 'x' })])).toMatchObject({ sortBy: VideoSortOption.Loved });
  });

  it('moves back to the last page when the results shrink below the one on screen', async () => {
    /*
      Given a search showing page 3 of 3
      When videos are deleted elsewhere and only 2 pages remain
      Then page 2 is opened
    */
    await openSearch({ page: 1 });
    await answer([aSearchedVideo()], { totalCount: 30 });
    await showPage(3, 3);

    TestBed.inject(VideoUpdateEventService).emitVideosDeleted(['gone']);
    await answer([], { totalCount: 20 });

    expect(url()).toBe('/search?currentPageNumber=2');
  });
});
