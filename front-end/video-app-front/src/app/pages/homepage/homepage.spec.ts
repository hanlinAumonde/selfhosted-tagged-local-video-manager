import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Location } from '@angular/common';
import { provideRouter, Router } from '@angular/router';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatButtonHarness } from '@angular/material/button/testing';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';

import { Homepage } from './homepage';
import { GetTopTagsDocument, SearchVideosDocument, VideoSortOption } from '../../core/graphql/generated/graphql';
import { HttpClientService } from '../../services/Http-client-service/Http-client.service';
import { PageStateService } from '../../services/Page-state-service/page-state.service';
import { VideoUpdateEventService } from '../../services/video-update-event-service/video-update-event.service';
import { SearchedVideo } from '../../shared/models/GQL-result.model';
import { apolloAsInTheApp } from '../../../testing/apollo-testing';
import { FakeThumbnails, fakeBlobUrls } from '../../../testing/thumbnail-fixtures';
import { aSearchedVideo } from '../../../testing/video-fixtures';

const tick = () => new Promise<void>(resolve => setTimeout(resolve));
const RAILS = ['Loved Videos', 'Latest Viewed', 'Last Updated', 'Most Viewed'];
const SORT_OF_RAIL = [VideoSortOption.Loved, VideoSortOption.Latest, VideoSortOption.LastUpdate, VideoSortOption.MostViewed];

describe('Homepage', () => {
  let fixture: ComponentFixture<Homepage>;
  let apollo: ApolloTestingController;

  beforeEach(async () => {
    fakeBlobUrls();
    TestBed.configureTestingModule({
      imports: [ApolloTestingModule],
      providers: [
        provideRouter([{ path: 'search', children: [] }]),
        { provide: HttpClientService, useValue: new FakeThumbnails() },
      ],
    });
    apollo = apolloAsInTheApp();
    fixture = TestBed.createComponent(Homepage);
    await settle();
  });

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  async function settle() {
    await tick();
    await fixture.whenStable();
  }

  /** Answers every rail still waiting, each with the videos given for its sort. */
  async function answerRails(videosBySort: Partial<Record<VideoSortOption, SearchedVideo[]>> = {}) {
    const pending = apollo.match(SearchVideosDocument);
    for (const op of pending) {
      const videos = videosBySort[op.operation.variables['input'].sortBy as VideoSortOption] ?? [];
      op.flushData({
        SearchVideos: {
          __typename: 'VideoSearchResult',
          pagination: { __typename: 'Pagination', size: 10, totalCount: videos.length, currentPageNumber: 1 },
          videos,
        },
      });
    }
    await settle();
    return pending.map(op => op.operation.variables['input'].sortBy);
  }

  async function answerTags(...tags: [string, number][]) {
    apollo.expectOne(GetTopTagsDocument).flushData({
      getTopTags: tags.map(([name, count]) => ({ __typename: 'VideoTag', name, count })),
    });
    await settle();
  }

  const element = () => fixture.nativeElement as HTMLElement;
  const rail = (title: string) =>
    [...element().querySelectorAll('section')].find(section => section.querySelector('h2')!.textContent!.trim() === title)!;
  const cardsIn = (title: string) =>
    [...rail(title).querySelectorAll('app-video-card')].map(card => card.querySelector('p.font-semibold')?.textContent!.trim() ?? '(placeholder)');
  const tagLinks = () => [...rail('Top Tags').querySelectorAll<HTMLAnchorElement>('a')];

  it('shows the four rails and the top tags', async () => {
    /*
      Given the home page is opened
      Then each rail shows placeholder cards while loading
      When "Loved" returns "a", "Latest" returns "b", "LastUpdate" returns "c", "MostViewed" returns "d"
      And the top tags are "cats" (3) and "dogs" (1)
      Then the four rails show "a", "b", "c" and "d" with a "More" button each
      And the tags read "cats (3)" and "dogs (1)"
    */
    for (const title of RAILS) expect(cardsIn(title).every(card => card === '(placeholder)')).toBe(true);

    await answerRails({
      [VideoSortOption.Loved]: [aSearchedVideo({ id: 'a' })],
      [VideoSortOption.Latest]: [aSearchedVideo({ id: 'b' })],
      [VideoSortOption.LastUpdate]: [aSearchedVideo({ id: 'c' })],
      [VideoSortOption.MostViewed]: [aSearchedVideo({ id: 'd' })],
    });
    await answerTags(['cats', 3], ['dogs', 1]);

    expect(RAILS.map(cardsIn)).toEqual([['a'], ['b'], ['c'], ['d']]);
    const more = await TestbedHarnessEnvironment.loader(fixture).getAllHarnesses(MatButtonHarness.with({ text: 'More' }));
    expect(more).toHaveLength(4);
    expect(tagLinks().map(a => a.textContent!.replace(/\s+/g, ' ').trim())).toEqual(['cats (3)', 'dogs (1)']);
  });

  it('says when a rail has nothing to show', async () => {
    /*
      Given every rail returns no videos
      Then each rail says why it is empty, with no "More" button
    */
    await answerRails();

    expect(RAILS.map(title => rail(title).querySelector('p.italic')?.textContent!.trim())).toEqual([
      'No loved videos yet. Show some love to your favorite videos!',
      'No viewed videos yet. Start watching some videos!',
      'No videos available. Check back later!',
      'No videos available. Check back later!',
    ]);
    expect(await TestbedHarnessEnvironment.loader(fixture).getAllHarnesses(MatButtonHarness.with({ text: 'More' }))).toHaveLength(0);
  });

  it('opens the search page sorted like the rail, on its first page', async () => {
    /*
      Given the home page is shown
      When the user clicks "More" on "Latest Viewed"
      Then the search page opens on page 1, sorted by Latest
      And the search state this tab kept is forgotten
    */
    await answerRails(Object.fromEntries(SORT_OF_RAIL.map(sort => [sort, [aSearchedVideo()]])));
    const states = TestBed.inject(PageStateService);
    states.setState('/search_refresh_key', { page: 4 }, false);

    const more = await TestbedHarnessEnvironment.loader(fixture).getAllHarnesses(MatButtonHarness.with({ text: 'More' }));
    await more[1].click();
    await settle();

    expect(TestBed.inject(Router).url).toBe('/search?currentPageNumber=1');
    expect(TestBed.inject(Location).getState()).toMatchObject({ sortBy: VideoSortOption.Latest });
    expect(states.getState('/search_refresh_key', false)).toBeUndefined();
  });

  it('opens a tag in a new tab, handing it over to that tab', async () => {
    /*
      Given the top tags hold "cats"
      Then "cats" links to the search page on page 1, in a new tab
      When the user clicks "cats"
      Then the tag "cats" is handed over to the tab that opens
    */
    await answerRails();
    await answerTags(['cats', 3]);
    const [cats] = tagLinks();

    expect([cats.getAttribute('href'), cats.target]).toEqual(['/search?currentPageNumber=1', '_blank']);

    cats.click();
    expect(TestBed.inject(PageStateService).getState('/search', true)).toEqual({ tags: ['cats'] });
  });

  it('refreshes every rail and the tags when a video changes anywhere', async () => {
    /*
      Given the home page shows its rails, none holding video "x"
      When "x" is updated, for example loved in another tab
      Then every rail and the tags are asked for again, so "x" can join the rails it now belongs in
      When a whole directory is deleted
      Then every rail and the tags are asked for again
    */
    await answerRails(Object.fromEntries(SORT_OF_RAIL.map(sort => [sort, [aSearchedVideo()]])));
    await answerTags(['cats', 3]);
    const events = TestBed.inject(VideoUpdateEventService);

    events.emitUpdated(['x']);
    await settle();
    expect((await answerRails()).sort()).toEqual([...SORT_OF_RAIL].sort());
    await answerTags();

    events.emitDirectoryDeleted('local/movies');
    await settle();
    expect((await answerRails()).sort()).toEqual([...SORT_OF_RAIL].sort());
    await answerTags();
  });
});
