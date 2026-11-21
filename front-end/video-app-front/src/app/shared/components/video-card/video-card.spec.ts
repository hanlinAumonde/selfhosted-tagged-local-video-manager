import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { VideoCard } from './video-card';
import { HttpClientService } from '../../../services/Http-client-service/Http-client.service';
import { SearchedVideo } from '../../models/GQL-result.model';
import { FakeThumbnails, fakeBlobUrls } from '../../../../testing/thumbnail-fixtures';
import { aSearchedVideo } from '../../../../testing/video-fixtures';

describe('VideoCard', () => {
  let fixture: ComponentFixture<VideoCard>;
  let thumbnails: FakeThumbnails;
  let blobs: ReturnType<typeof fakeBlobUrls>;

  beforeEach(() => {
    blobs = fakeBlobUrls();
    thumbnails = new FakeThumbnails();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), { provide: HttpClientService, useValue: thumbnails }],
    });
    fixture = TestBed.createComponent(VideoCard);
  });

  async function show(video: SearchedVideo | null) {
    fixture.componentRef.setInput('video', video);
    await fixture.whenStable();
  }

  const element = () => fixture.nativeElement as HTMLElement;
  const text = () => element().textContent!.replace(/\s+/g, ' ').trim();
  const link = () => element().querySelector('a');
  const image = () => element().querySelector('img')?.getAttribute('src');
  const views = () =>
    [...element().querySelectorAll('p')].map(p => p.textContent!.trim()).find(t => t.endsWith('Views'))!.replace(' Views', '');

  it('shows a placeholder while there is no video', async () => {
    /*
      Given the card has no video
      Then it shows no link and no text
    */
    await show(null);

    expect(link()).toBeNull();
    expect(text()).toBe('');
  });

  it('shows the video and links to its page', async () => {
    /*
      Given video "trip" named "Trip", by "bob", 1:01:05 long, viewed 1520 times
      Then the card shows "Trip", "bob", "1:01:05" and "1.5K Views"
      And it links to "/video/trip"
    */
    await show(aSearchedVideo({ id: 'trip', name: 'Trip', author: 'bob', duration: 3665, viewCount: 1520 }));

    for (const part of ['Trip', 'bob', '1:01:05', '1.5K Views']) expect(text()).toContain(part);
    expect(link()!.getAttribute('href')).toBe('/video/trip');
  });

  it('shortens view counts and durations', async () => {
    /*
      Given a video viewed 0, 999, 1000, 2_500_000 times and 65 seconds long
      Then the views read "0", "999", "1K", "2.5M"
      And the duration reads "1:05"
      Given instead a video with no duration
      Then no duration is shown
    */
    const shown = [];
    for (const viewCount of [0, 999, 1000, 2_500_000]) {
      await show(aSearchedVideo({ id: 'v', viewCount, duration: 65 }));
      shown.push(views());
      expect(text()).toContain('1:05');
    }
    expect(shown).toEqual(['0', '999', '1K', '2.5M']);

    await show(aSearchedVideo({ id: 'v', duration: 0 }));
    expect(text()).not.toMatch(/\d+:\d\d/);
  });

  it('cannot be opened while a migration holds the video', async () => {
    /*
      Given video "busy" is held by a migration
      Then the card says "Migrating" and has no link
    */
    await show(aSearchedVideo({ id: 'busy', isLocked: true }));

    expect(text()).toContain('Migrating');
    expect(link()!.hasAttribute('href')).toBe(false);
  });

  it('shows the thumbnail once it arrives', async () => {
    /*
      Given video "trip"
      Then the default icon is shown
      When its thumbnail arrives
      Then the thumbnail is shown
    */
    await show(aSearchedVideo({ id: 'trip' }));
    expect(image()).toBe('/videoicon.png');

    thumbnails.arrive('trip');
    await fixture.whenStable();

    expect(image()).toBe('blob:1');
  });

  it('keeps its thumbnail across a refresh and releases it when it goes away', async () => {
    /*
      Given the thumbnail of video "trip" is shown
      When the page hands the card a refreshed copy of "trip"
      Then the same thumbnail stays, without fetching it again
      When the card is destroyed
      Then the image is released
    */
    await show(aSearchedVideo({ id: 'trip' }));
    thumbnails.arrive('trip');
    await fixture.whenStable();

    await show(aSearchedVideo({ id: 'trip', viewCount: 1 }));
    expect(image()).toBe('blob:1');
    expect(thumbnails.requestedIds()).toEqual(['trip']);

    fixture.destroy();
    expect(blobs.revoked).toEqual(['blob:1']);
  });
});
