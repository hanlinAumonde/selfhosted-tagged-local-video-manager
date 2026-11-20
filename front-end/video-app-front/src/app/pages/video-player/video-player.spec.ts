import { DeferBlockBehavior, DeferBlockState, TestBed } from '@angular/core/testing';
import { Title } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { MatDialog } from '@angular/material/dialog';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';
import { Subject } from 'rxjs';
import { MockInstance } from 'vitest';

import { VideoPlayer } from './video-player';
import {
  GetVideoByIdDocument,
  RecordVideoViewDocument,
  UpdateVideoMetadataDocument,
} from '../../core/graphql/generated/graphql';
import { HttpClientService } from '../../services/Http-client-service/Http-client.service';
import { PageStateService } from '../../services/Page-state-service/page-state.service';
import { ToastService } from '../../services/toast-service/toast.service';
import { VideoUpdateEventService } from '../../services/video-update-event-service/video-update-event.service';
import { ResultState, VideoDetail } from '../../shared/models/GQL-result.model';
import { ToastType } from '../../shared/models/toast.model';
import { VideoEditPanel } from '../../shared/components/video-edit-panel/video-edit-panel';
import { apolloAsInTheApp } from '../../../testing/apollo-testing';
import { FakeThumbnails, fakeBlobUrls } from '../../../testing/thumbnail-fixtures';
import { aVideoDetail } from '../../../testing/video-fixtures';

const tick = () => new Promise<void>(resolve => setTimeout(resolve));
const loaded = (video: VideoDetail): ResultState<VideoDetail | null> => ({ loading: false, error: null, data: video });
const withTags = (...names: string[]) => names.map(name => ({ __typename: 'VideoTag' as const, name }));

describe('VideoPlayer', () => {
  let harness: RouterTestingHarness;
  let apollo: ApolloTestingController;
  let toast: MockInstance<ToastService['emitNewToast']>;
  let dialog: { open: ReturnType<typeof vi.fn> };
  let closed: Subject<unknown>;
  let resolved: ResultState<VideoDetail | null>;

  async function openPage(state: ResultState<VideoDetail | null>) {
    resolved = state;
    fakeBlobUrls();
    closed = new Subject();
    dialog = { open: vi.fn(() => ({ afterClosed: () => closed })) };
    TestBed.configureTestingModule({
      imports: [ApolloTestingModule],
      providers: [
        provideRouter([
          { path: 'video/:id', component: VideoPlayer, resolve: { video: () => resolved } },
          { path: '**', children: [] },
        ]),
        { provide: HttpClientService, useValue: new FakeThumbnails() },
        { provide: MatDialog, useValue: dialog },
      ],
      deferBlockBehavior: DeferBlockBehavior.Manual,
    });
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
    harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(`/video/${state.data?.id ?? 'v1'}`);
    await settle();
  }

  const openVideo = (overrides: Partial<VideoDetail> = {}) => openPage(loaded(aVideoDetail({ id: 'v1', ...overrides })));

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  async function settle() {
    await tick();
    await harness.fixture.whenStable();
  }

  async function showPlayer() {
    const [player] = await harness.fixture.getDeferBlocks();
    await player.render(DeferBlockState.Complete);
    await settle();
  }

  async function play() {
    page().querySelector('video')!.dispatchEvent(new Event('play'));
    await settle();
  }

  const page = () => harness.routeNativeElement!;
  const text = () => page().textContent!.replace(/\s+/g, ' ');
  const heart = () => page().querySelector<HTMLButtonElement>('#love-icon')!;
  const linkTo = (label: string) =>
    [...page().querySelectorAll<HTMLAnchorElement>('a')].find(a => a.textContent!.trim() === label)!;

  function answerUpdate(video: Partial<VideoDetail> | null) {
    apollo.expectOne(UpdateVideoMetadataDocument).flushData({
      updateVideoMetadata: {
        __typename: 'VideoMutationResult',
        success: !!video,
        video: video && {
          __typename: 'Video', id: 'v1', name: 'Trip', author: 'bob', loved: false, introduction: '',
          seriesName: null, seriesOrder: null, tags: [], ...video,
        },
      },
    });
    return settle();
  }

  it('shows the video it was opened on', async () => {
    /*
      Given video "v1" named "Trip", by "bob", introduced as "Holiday", tagged "beach", viewed 1520 times,
        3rd in series "Saga"
      When its page is opened
      Then the page shows "Trip", "bob", "Holiday", "beach", "1.5K" and "Saga #3"
      And the tab title is "Trip - Tagged Local Video App"
      And the player streams "/video/stream/v1"
      And the series panel lists "Saga"
    */
    await openVideo({
      name: 'Trip', author: 'bob', introduction: 'Holiday', tags: withTags('beach'), viewCount: 1520,
      seriesName: 'Saga', seriesOrder: 3,
    });
    await showPlayer();

    for (const part of ['Trip', 'bob', 'Holiday', 'beach', '1.5K', 'Saga #3']) expect(text()).toContain(part);
    expect(TestBed.inject(Title).getTitle()).toBe('Trip - Tagged Local Video App');
    expect(page().querySelector('video')!.getAttribute('src')).toMatch(/\/video\/stream\/v1$/);
    expect(page().querySelector('app-series-panel h2')!.textContent!.trim()).toBe('Saga');
    // The first render of the player pulls in the whole Video.js chunk, slow under coverage.
  }, 20_000);

  it('says when the video failed to load', async () => {
    /*
      Given loading the video failed
      When its page is opened
      Then it says "Failed to load video"
    */
    await openPage({ loading: false, error: 'boom', data: null });

    expect(text()).toContain('Failed to load video');
  });

  it('counts a view once, the first time the video plays', async () => {
    /*
      Given the page of video "v1" viewed 4 times
      When the video starts playing
      Then a view of "v1" is recorded
      When the backend answers with 5 views
      Then the page shows 5 views
      When the video plays again
      Then no further view is recorded
    */
    await openVideo({ viewCount: 4 });
    await showPlayer();

    await play();
    const op = apollo.expectOne(RecordVideoViewDocument);
    expect(op.operation.variables).toEqual({ videoId: 'v1' });
    op.flushData({
      recordVideoView: { __typename: 'VideoMutationResult', success: true, video: { __typename: 'Video', id: 'v1', viewCount: 5, lastViewTime: 1 } },
    });
    await settle();
    expect(text()).toContain('Views: 5');

    await play();
    apollo.expectNone(RecordVideoViewDocument);
  });

  it('says when the view could not be recorded', async () => {
    /*
      Given the page of video "v1"
      When the video starts playing and recording the view fails
      Then an error toast says the view was not recorded
    */
    await openVideo();
    await showPlayer();

    await play();
    apollo.expectOne(RecordVideoViewDocument).flushData({
      recordVideoView: { __typename: 'VideoMutationResult', success: false, video: null },
    });
    await settle();

    expect(toast).toHaveBeenCalledWith('Failed to record video view', ToastType.Error);
  });

  it('loves the video and tells the other pages', async () => {
    /*
      Given the page of video "v1", not loved, tagged "beach"
      When the user clicks the heart
      Then "v1" is saved as loved with its tag "beach" kept
      When the backend confirms
      Then the heart is filled and the update of "v1" is announced
    */
    await openVideo({ loved: false, tags: withTags('beach') });
    const announced = vi.spyOn(TestBed.inject(VideoUpdateEventService), 'emitUpdated').mockImplementation(() => {});

    heart().click();
    await settle();
    const op = apollo.expectOne(UpdateVideoMetadataDocument);
    expect(op.operation.variables['input']).toMatchObject({ videoId: 'v1', loved: true, tags: ['beach'] });
    op.flushData({
      updateVideoMetadata: {
        __typename: 'VideoMutationResult',
        success: true,
        video: {
          __typename: 'Video', id: 'v1', name: 'v1', author: '', loved: true, introduction: '',
          seriesName: null, seriesOrder: null, tags: withTags('beach'),
        },
      },
    });
    await settle();

    expect(heart().textContent!.trim()).toBe('favorite');
    expect(announced).toHaveBeenCalledWith(['v1']);
  });

  it('says when loving the video failed', async () => {
    /*
      Given the page of video "v1", not loved
      When the user clicks the heart and the backend refuses
      Then an error toast says so and the heart stays empty
    */
    await openVideo({ loved: false });

    heart().click();
    await settle();
    await answerUpdate(null);

    expect(toast).toHaveBeenCalledWith('Failed to update loved status', ToastType.Error);
    expect(heart().textContent!.trim()).toBe('favorite_border');
  });

  it('shows the edits made in the edit panel', async () => {
    /*
      Given the page of video "v1" named "Trip"
      When the user opens the edit panel
      Then the panel opens in full mode on "v1"
      When the panel closes having renamed it "Trip 2" and moved it to series "Epic" #1
      Then the page shows "Trip 2" and "Epic #1"
      When the user opens the panel again and dismisses it
      Then the page still shows "Trip 2"
    */
    await openVideo({ name: 'Trip' });
    const editButton = () => page().querySelector<HTMLButtonElement>('button:has(mat-icon[fonticon="build"])')!;

    editButton().click();
    const [component, config] = dialog.open.mock.lastCall!;
    expect(component).toBe(VideoEditPanel);
    expect(config).toMatchObject({ data: { mode: 'full', video: { id: 'v1' } } });

    closed.next({
      success: true,
      video: { id: 'v1', name: 'Trip 2', author: '', loved: false, introduction: '', seriesName: 'Epic', seriesOrder: 1, tags: [] },
    });
    closed.complete();
    await settle();
    expect(page().querySelector('h1')!.textContent).toBe('Trip 2');
    expect(text()).toContain('Epic #1');

    closed = new Subject();
    editButton().click();
    closed.next(undefined);
    await settle();
    expect(page().querySelector('h1')!.textContent).toBe('Trip 2');
  });

  it('hands the author or a tag over to the search tab it opens', async () => {
    /*
      Given the page of video "v1" by "bob", tagged "beach"
      Then "bob" and "beach" link to the search page on page 1, in a new tab
      When the user clicks "bob"
      Then the author "bob" is handed over to the tab that opens
      When the user clicks "beach"
      Then the tag "beach" is handed over to the tab that opens
    */
    await openVideo({ author: 'bob', tags: withTags('beach') });
    const states = TestBed.inject(PageStateService);

    for (const label of ['bob', 'beach']) {
      expect([linkTo(label).getAttribute('href'), linkTo(label).target]).toEqual(['/search?currentPageNumber=1', '_blank']);
    }

    linkTo('bob').click();
    expect(states.getState('/search', true)).toEqual({ author: 'bob' });

    linkTo('beach').click();
    expect(states.getState('/search', true)).toEqual({ tags: ['beach'] });
  });

  it('reloads the video when it is changed elsewhere', async () => {
    /*
      Given the page of video "v1" named "Trip"
      When another video "x" is updated
      Then "v1" is not asked for again
      When "v1" is updated elsewhere
      Then "v1" is asked for again
      When it arrives renamed "Trip 2"
      Then the page shows "Trip 2"
    */
    await openVideo({ name: 'Trip' });
    const events = TestBed.inject(VideoUpdateEventService);

    events.emitUpdated(['x']);
    await settle();
    apollo.expectNone(GetVideoByIdDocument);

    events.emitUpdated(['v1']);
    await settle();
    const op = apollo.expectOne(GetVideoByIdDocument);
    expect(op.operation.variables).toEqual({ videoId: 'v1' });
    op.flushData({ getVideoById: aVideoDetail({ id: 'v1', name: 'Trip 2' }) });
    await settle();

    expect(page().querySelector('h1')!.textContent).toBe('Trip 2');
  });

  it('leaves for the home page when the video is deleted elsewhere', async () => {
    /*
      Given the page of video "v1"
      When "v1" is deleted elsewhere
      Then a warning toast says the video was deleted
      And the user lands on the home page
    */
    await openVideo();

    TestBed.inject(VideoUpdateEventService).emitVideosDeleted(['v1']);
    await settle();

    expect(toast).toHaveBeenCalledWith('The video you are watching has been deleted.', ToastType.Warning);
    expect(TestBed.inject(Router).url).toBe('/');
  });
});
