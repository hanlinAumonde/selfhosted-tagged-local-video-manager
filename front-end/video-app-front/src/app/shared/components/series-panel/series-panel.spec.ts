import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';

import { SeriesPanel } from './series-panel';
import { GetSeriesVideosDocument } from '../../../core/graphql/generated/graphql';
import { HttpClientService } from '../../../services/Http-client-service/Http-client.service';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import { apolloAsInTheApp } from '../../../../testing/apollo-testing';
import { FakeThumbnails, fakeBlobUrls } from '../../../../testing/thumbnail-fixtures';

const tick = () => new Promise<void>(resolve => setTimeout(resolve));
const member = (id: string, seriesOrder: number | null, overrides: { duration?: number; isLocked?: boolean } = {}) =>
  ({ __typename: 'Video', id, name: id, seriesOrder, thumbnail: null, duration: 60, isLocked: false, ...overrides });

describe('SeriesPanel', () => {
  let fixture: ComponentFixture<SeriesPanel>;
  let apollo: ApolloTestingController;
  let thumbnails: FakeThumbnails;
  let blobs: ReturnType<typeof fakeBlobUrls>;
  let scrolledTo: string[];

  async function showPanel(seriesName: string | null, currentVideoId = 'v2') {
    blobs = fakeBlobUrls();
    thumbnails = new FakeThumbnails();
    scrolledTo = [];
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolledTo.push(this.textContent!.replace(/\s+/g, ' ').trim());
    };
    TestBed.configureTestingModule({
      imports: [ApolloTestingModule],
      providers: [provideRouter([]), { provide: HttpClientService, useValue: thumbnails }],
    });
    apollo = apolloAsInTheApp();
    fixture = TestBed.createComponent(SeriesPanel);
    fixture.componentRef.setInput('seriesName', seriesName);
    fixture.componentRef.setInput('currentVideoId', currentVideoId);
    await settle();
  }

  afterEach(() => {
    delete (Element.prototype as Partial<Element>).scrollIntoView;
  });

  async function settle() {
    await tick();
    await fixture.whenStable();
    await tick();
  }

  async function answer(series: string, ...members: ReturnType<typeof member>[]) {
    const [op, ...others] = apollo.match(GetSeriesVideosDocument).filter(op => op.operation.variables['name'] === series);
    expect(others).toHaveLength(0);
    op.flushData({ getSeriesVideos: members });
    await settle();
  }

  const element = () => fixture.nativeElement as HTMLElement;
  const text = () => element().textContent!.replace(/\s+/g, ' ').trim();
  const entries = () => [...element().querySelectorAll('li')];
  const entry = (id: string) => entries().find(li => li.querySelector('img')!.getAttribute('alt') === id)!;
  /** "order. name" per entry, as the user reads it. */
  const listed = () => entries().map(li => li.querySelector('a')!.lastElementChild!.textContent!.trim())
    .map((name, i) => `${entries()[i].querySelector('span')!.textContent!.trim()} ${name}`);
  const isLoading = () => !!element().querySelector('mat-progress-spinner');

  it('shows nothing when the video is in no series', async () => {
    /*
      Given the video is in no series
      Then the panel shows nothing and asks for no series
    */
    await showPanel(null);

    expect(text()).toBe('');
    apollo.verify();
  });

  it('lists the series with the current video highlighted and scrolled into view', async () => {
    /*
      Given the video "v2" is in series "Saga"
      Then the panel shows "Saga" and is loading
      When the series arrives holding "v1" (1:05) and "v2", ordered 1 and 2
      Then it lists "1. v1" and "2. v2", with "v2" highlighted and scrolled into view
      And each entry links to its video page
    */
    await showPanel('Saga', 'v2');
    expect(text()).toContain('Saga');
    expect(isLoading()).toBe(true);

    await answer('Saga', member('v1', 1, { duration: 65 }), member('v2', 2));

    expect(listed()).toEqual(['1. v1', '2. v2']);
    expect(entry('v1').textContent).toContain('1:05');
    expect(entries().map(li => li.classList.contains('bg-blue-100'))).toEqual([false, true]);
    expect(scrolledTo.at(-1)).toContain('v2');
    expect(entries().map(li => li.querySelector('a')!.getAttribute('href'))).toEqual(['/video/v1', '/video/v2']);
  });

  it('says when the series failed to load or holds nothing', async () => {
    /*
      Given the video is in series "Saga"
      When the series fails to load
      Then the panel says "Failed to load series"
      Given instead the series "Empty" holds no videos
      Then the panel says "No videos in this series."
    */
    await showPanel('Saga');
    apollo.expectOne(GetSeriesVideosDocument).networkError(new Error('down'));
    await settle();
    expect(text()).toContain('Failed to load series');

    fixture.componentRef.setInput('seriesName', 'Empty');
    await settle();
    await answer('Empty');
    expect(text()).toContain('No videos in this series.');
  });

  it('cannot open a video that a migration holds', async () => {
    /*
      Given series "Saga" holds video "busy" that a migration holds
      Then the entry of "busy" has no link
    */
    await showPanel('Saga');
    await answer('Saga', member('v1', 1), member('busy', 2, { isLocked: true }));

    expect(entry('busy').querySelector('a')!.hasAttribute('href')).toBe(false);
    expect(entry('v1').querySelector('a')!.hasAttribute('href')).toBe(true);
  });

  it('reloads in place when one of its videos changes', async () => {
    /*
      Given series "Saga" holding "v1" and "v2" is listed, for current video "v2"
      When another video "x" is updated
      Then the series is not asked for again
      When "v1" is updated
      Then the series is asked for again, and the list stays on screen while it loads
      When the series arrives in a new order
      Then the new order is listed
    */
    await showPanel('Saga', 'v2');
    await answer('Saga', member('v1', 1), member('v2', 2));
    const events = TestBed.inject(VideoUpdateEventService);

    events.emitUpdated(['x']);
    await settle();
    apollo.verify();

    events.emitUpdated(['v1']);
    await settle();
    expect(isLoading()).toBe(false);
    expect(listed()).toEqual(['1. v1', '2. v2']);

    await answer('Saga', member('v2', 1), member('v1', 2));
    expect(listed()).toEqual(['1. v2', '2. v1']);
  });

  it('shows the thumbnails of its videos and releases them when it goes away', async () => {
    /*
      Given series "Saga" holding "v1" and "v2" is listed
      When the thumbnail of "v1" arrives
      Then "v1" shows it and "v2" the default icon
      When the panel is destroyed
      Then the thumbnail of "v1" is released
    */
    await showPanel('Saga');
    await answer('Saga', member('v1', 1), member('v2', 2));

    thumbnails.arrive('v1');
    await settle();
    expect(['v1', 'v2'].map(id => entry(id).querySelector('img')!.getAttribute('src'))).toEqual(['blob:1', '/videoicon.png']);

    fixture.destroy();
    expect(blobs.revoked).toEqual(['blob:1']);
  });
});
