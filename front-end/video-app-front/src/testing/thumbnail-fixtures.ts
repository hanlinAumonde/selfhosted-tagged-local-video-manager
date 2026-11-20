import { HttpResponse } from '@angular/common/http';
import { Observable, Subscriber } from 'rxjs';

import { HttpClientService } from '../app/services/Http-client-service/Http-client.service';

interface PendingThumbnail {
  videoId: string;
  subscriber: Subscriber<HttpResponse<Blob>>;
  abandoned: boolean;
}

/**
 * Stands in for HttpClientService's thumbnail fetch: every request waits until the test
 * answers it, so a test decides when, and in which order, thumbnails arrive.
 */
export class FakeThumbnails implements Pick<HttpClientService, 'getThumbnailUrl'> {
  readonly requests: PendingThumbnail[] = [];

  getThumbnailUrl(videoId: string): Observable<HttpResponse<Blob>> {
    return new Observable(subscriber => {
      const request = { videoId, subscriber, abandoned: false };
      this.requests.push(request);
      return () => (request.abandoned = true);
    });
  }

  /** Answers the latest request for `videoId`; `null` answers with an empty body. */
  arrive(videoId: string, body: Blob | null = new Blob(['img'])) {
    const request = this.latest(videoId);
    request.subscriber.next(new HttpResponse({ body }));
    request.subscriber.complete();
  }

  fail(videoId: string) {
    this.latest(videoId).subscriber.error(new Error('thumbnail failed'));
  }

  isAbandoned(videoId: string): boolean {
    return this.latest(videoId).abandoned;
  }

  requestedIds(): string[] {
    return this.requests.map(request => request.videoId);
  }

  private latest(videoId: string): PendingThumbnail {
    const found = this.requests.filter(request => request.videoId === videoId).at(-1);
    if (!found) throw new Error(`no thumbnail was requested for ${videoId}`);
    return found;
  }
}

/**
 * jsdom has no blob URLs. Each created URL is `blob:N`, so a test can tell which image a
 * tile shows and which ones were released. Call in `beforeEach`; `vi.restoreAllMocks()`
 * is not needed since the properties are replaced, not spied.
 */
export function fakeBlobUrls() {
  let next = 1;
  const revoked: string[] = [];
  Object.defineProperty(URL, 'createObjectURL', { value: () => `blob:${next++}`, configurable: true });
  Object.defineProperty(URL, 'revokeObjectURL', { value: (url: string) => revoked.push(url), configurable: true });
  return { revoked };
}
