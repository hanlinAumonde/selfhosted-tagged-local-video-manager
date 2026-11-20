import { ComponentFixture, TestBed } from '@angular/core/testing';

import { FileThumbnail } from './file-thumbnail';
import { HttpClientService } from '../../../services/Http-client-service/Http-client.service';
import { FakeThumbnails, fakeBlobUrls } from '../../../../testing/thumbnail-fixtures';

describe('FileThumbnail', () => {
  let fixture: ComponentFixture<FileThumbnail>;
  let thumbnails: FakeThumbnails;
  let blobs: ReturnType<typeof fakeBlobUrls>;

  beforeEach(async () => {
    blobs = fakeBlobUrls();
    thumbnails = new FakeThumbnails();
    TestBed.configureTestingModule({ providers: [{ provide: HttpClientService, useValue: thumbnails }] });
    fixture = TestBed.createComponent(FileThumbnail);
    await showVideo('v1');
  });

  async function showVideo(id: string) {
    fixture.componentRef.setInput('videoId', id);
    await fixture.whenStable();
  }

  async function settle() {
    await fixture.whenStable();
  }

  const shown = () => (fixture.nativeElement as HTMLElement).querySelector('img')!.getAttribute('src');

  it('shows the default icon until the thumbnail arrives', async () => {
    /*
      Given a thumbnail for video "v1" is being fetched
      Then the default icon is shown
      When the thumbnail arrives
      Then the thumbnail is shown
    */
    expect(shown()).toBe('/videoicon.png');

    thumbnails.arrive('v1');
    await settle();

    expect(shown()).toBe('blob:1');
  });

  it('keeps the default icon when the thumbnail cannot be loaded', async () => {
    /*
      Given the thumbnail for video "v1" is being fetched
      When the fetch fails, or the response has no image
      Then the default icon stays
    */
    thumbnails.fail('v1');
    await settle();
    expect(shown()).toBe('/videoicon.png');

    await showVideo('v2');
    thumbnails.arrive('v2', null);
    await settle();
    expect(shown()).toBe('/videoicon.png');
  });

  it('shows only the thumbnail of the video it is showing now', async () => {
    /*
      Given the thumbnail for video "v1" is being fetched
      When the tile switches to video "v2" before it arrives
      Then the fetch for "v1" is abandoned
      When the thumbnail of "v2" arrives
      Then it is shown, and the image of "v1" never is
    */
    await showVideo('v2');
    expect(thumbnails.isAbandoned('v1')).toBe(true);

    thumbnails.arrive('v2');
    await settle();

    expect(shown()).toBe('blob:1');
  });

  it('releases the image it holds when it goes away', async () => {
    /*
      Given the thumbnail of video "v1" is shown
      When the tile switches to "v2" and its thumbnail arrives
      Then the image of "v1" is released
      When the tile is destroyed
      Then the image of "v2" is released
    */
    thumbnails.arrive('v1');
    await settle();

    await showVideo('v2');
    thumbnails.arrive('v2');
    await settle();
    expect(blobs.revoked).toEqual(['blob:1']);

    fixture.destroy();
    expect(blobs.revoked).toEqual(['blob:1', 'blob:2']);
  });
});
