import { Component, DestroyRef, effect, inject, input, signal, ChangeDetectionStrategy } from '@angular/core';
import { HttpClientService } from '../../../services/Http-client-service/Http-client.service';

/**
 * One video's thumbnail, shown as the default video icon until the image arrives.
 *
 * Meant to be created inside `@defer (on viewport)`: a directory can hold hundreds of
 * files, and the backend generates a missing thumbnail with ffmpeg on first request —
 * only the tiles someone actually scrolls to should pay for that.
 */
@Component({
  selector: 'app-file-thumbnail',
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'block w-full h-full' },
  template: `
    <img
      [src]="objectUrl() ?? defaultThumbnail"
      [alt]="alt()"
      class="w-full h-full"
      [class.object-cover]="objectUrl() !== null"
      [class.object-contain]="objectUrl() === null"
      [class.p-6]="objectUrl() === null"
    />
  `
})
export class FileThumbnail {
  videoId = input.required<string>();
  alt = input<string>('');

  readonly defaultThumbnail = '/videoicon.png';
  objectUrl = signal<string | null>(null);

  private httpClientService = inject(HttpClientService);

  constructor() {
    effect(onCleanup => {
      const subscription = this.httpClientService.getThumbnailUrl(this.videoId()).subscribe({
        next: response => this.replaceObjectUrl(response.body ? URL.createObjectURL(response.body) : null),
        // ImageRequestInterceptor already reports the failure; the default icon stays.
        error: () => {}
      });
      onCleanup(() => subscription.unsubscribe());
    });

    inject(DestroyRef).onDestroy(() => this.replaceObjectUrl(null));
  }

  /** Blob URLs pin their image in memory until revoked; a long directory would accumulate them. */
  private replaceObjectUrl(url: string | null) {
    const previous = this.objectUrl();
    if (previous) URL.revokeObjectURL(previous);
    this.objectUrl.set(url);
  }
}
