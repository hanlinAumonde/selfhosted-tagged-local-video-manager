import { ComponentFixture, TestBed } from '@angular/core/testing';

import { VideoPlayerHost } from './video-player-host';

describe('VideoPlayerHost', () => {
  let fixture: ComponentFixture<VideoPlayerHost>;

  beforeEach(async () => {
    fixture = TestBed.createComponent(VideoPlayerHost);
    await fixture.whenStable();
  });

  const video = () => (fixture.nativeElement as HTMLElement).querySelector('video')!;

  it('loads nothing until the stream is known', async () => {
    /*
      Given the stream address is not known yet
      Then the video has no source
      When the address becomes "/video/stream/v1"
      Then the video plays from "/video/stream/v1"
    */
    expect(video().hasAttribute('src')).toBe(false);

    fixture.componentRef.setInput('src', '/video/stream/v1');
    await fixture.whenStable();

    expect(video().getAttribute('src')).toBe('/video/stream/v1');
  });

  it('reports when the video starts playing', async () => {
    /*
      Given the player shows a video
      When the video starts playing
      Then a play is reported
    */
    const played = vi.fn();
    fixture.componentInstance.played.subscribe(played);
    fixture.componentRef.setInput('src', '/video/stream/v1');
    await fixture.whenStable();

    video().dispatchEvent(new Event('play'));

    expect(played).toHaveBeenCalledTimes(1);
  });
});
