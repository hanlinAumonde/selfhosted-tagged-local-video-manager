/*
  Two slot implementations sit behind getThumbnailUrl(): one on the Web Locks API (shared by
  every tab) and a per-tab fallback for when it is missing. The shared contract runs against
  both; jsdom has no Web Locks, so the cross-tab run borrows Node's real LockManager.
*/
import { HttpRequest, HttpResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Subscription } from 'rxjs';

import { HttpClientService } from './Http-client.service';
import { environment } from '../../../environments/environment';

const THUMBNAIL_URL = environment.backend_api + environment.videopage_thumbnail_api;

/** Node's process-wide LockManager; reached at runtime because the spec build has no Node types. */
async function nodeLockManager(): Promise<LockManager> {
  const module = 'node:worker_threads';
  return (await import(/* @vite-ignore */ module)).locks;
}

interface Caller {
  responses: HttpResponse<Blob>[];
  error: unknown;
  subscription: Subscription;
}

describe('HttpClientService', () => {
  let locks: LockManager;
  let http: HttpTestingController;
  let sent: TestRequest[];
  let callers: Caller[];

  beforeAll(async () => (locks = await nodeLockManager()));

  function setUp(withLocks: boolean) {
    if (withLocks) Object.defineProperty(navigator, 'locks', { value: locks, configurable: true });
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    sent = [];
    callers = [];
  }

  afterEach(async () => {
    callers.forEach(caller => caller.subscription.unsubscribe());
    // A slot left held would leak into the next test through the shared lock manager.
    await vi.waitFor(async () => {
      const state = await locks.query();
      expect([state.held?.length, state.pending?.length]).toEqual([0, 0]);
    });
    delete (navigator as { locks?: LockManager }).locks;
  });

  /** A new tab: its own service instance, as each tab has. */
  const openTab = () => TestBed.runInInjectionContext(() => new HttpClientService());

  function requestThumbnail(videoId: string, tab = TestBed.inject(HttpClientService)): Caller {
    const caller = { responses: [], error: undefined } as unknown as Caller;
    caller.subscription = tab.getThumbnailUrl(videoId).subscribe({
      next: response => caller.responses.push(response),
      error: error => (caller.error = error),
    });
    callers.push(caller);
    return caller;
  }

  const isThumbnail = (req: HttpRequest<unknown>) => req.url === THUMBNAIL_URL;
  const sentIds = () => sent.map(req => req.request.params.get('video_id'));

  /**
   * Waits until `sent` requests have gone out, then gives any request that should not go out
   * a moment to do so anyway. The lock manager's queue can't be counted instead: a waiter
   * queues on every slot, and Node keeps withdrawn entries listed until that lock is released.
   */
  async function expectRequests(expected: { sent: number }) {
    await vi.waitFor(() => {
      sent.push(...http.match(isThumbnail));
      expect(sent.length).toBe(expected.sent);
    });
    await new Promise(resolve => setTimeout(resolve, 50));
    sent.push(...http.match(isThumbnail));
    expect(sent.length).toBe(expected.sent);
  }

  const finish = (req: TestRequest) => req.flush(new Blob(['image']));
  const fail = (req: TestRequest) => req.flush(new Blob(['boom']), { status: 500, statusText: 'Server Error' });

  describe.each([
    ['with Web Locks', true],
    ['without Web Locks', false],
  ])('thumbnail slots %s', (_, withLocks) => {
    beforeEach(() => setUp(withLocks));

    it('fetches a thumbnail for the requested video', async () => {
      /*
        Given no thumbnail is loading
        When the thumbnail of video "v1" is requested
        Then one request is sent to the thumbnail endpoint with video_id "v1"
        And the image it returns is handed to the caller
      */
      const caller = requestThumbnail('v1');

      await expectRequests({ sent: 1 });
      expect(sentIds()).toEqual(['v1']);
      expect(sent[0].request.responseType).toBe('blob');

      const image = new Blob(['image']);
      sent[0].flush(image);
      expect(caller.responses.map(r => r.body)).toEqual([image]);
    });

    it('keeps at most three thumbnail requests in flight', async () => {
      /*
        Given no thumbnail is loading
        When thumbnails of five videos are requested
        Then only three requests are sent
        And the other two wait
      */
      ['v1', 'v2', 'v3', 'v4', 'v5'].forEach(id => requestThumbnail(id));

      await expectRequests({ sent: 3 });
      expect(sentIds()).toEqual(['v1', 'v2', 'v3']);
    });

    it('starts a waiting request when a running one finishes or fails', async () => {
      /*
        Given three thumbnail requests are running and two are waiting
        When one running request succeeds
        Then a fourth request is sent
        When another running request fails
        Then the fifth request is sent
        And the caller of the failed one receives the error
      */
      const [, second] = ['v1', 'v2', 'v3', 'v4', 'v5'].map(id => requestThumbnail(id));
      await expectRequests({ sent: 3 });

      finish(sent[0]);
      await expectRequests({ sent: 4 });

      fail(sent[1]);
      await expectRequests({ sent: 5 });
      expect(second.error).toMatchObject({ status: 500 });
    });

    it('never sends a request that was abandoned while waiting', async () => {
      /*
        Given three thumbnail requests are running and two are waiting
        When the caller of the first waiting request unsubscribes
        And all three running requests finish
        Then only the second waiting request is sent
        And no slot is left held
      */
      const [, , , firstWaiting] = ['v1', 'v2', 'v3', 'v4', 'v5'].map(id => requestThumbnail(id));
      await expectRequests({ sent: 3 });

      firstWaiting.subscription.unsubscribe();
      sent.slice(0, 3).forEach(finish);

      await expectRequests({ sent: 4 });
      expect(sentIds()).toEqual(['v1', 'v2', 'v3', 'v5']);
      finish(sent[3]);
      // Every slot is free again: three fresh requests all go straight out.
      ['v6', 'v7', 'v8'].forEach(id => requestThumbnail(id));
      await expectRequests({ sent: 7 });
    });

    it('frees the slot of a running request that is abandoned', async () => {
      /*
        Given three thumbnail requests are running and one is waiting
        When the caller of a running request unsubscribes
        Then that request is cancelled
        And the waiting request is sent
      */
      const [, running] = ['v1', 'v2', 'v3', 'v4'].map(id => requestThumbnail(id));
      await expectRequests({ sent: 3 });

      running.subscription.unsubscribe();

      expect(sent[1].cancelled).toBe(true);
      await expectRequests({ sent: 4 });
      expect(sentIds()[3]).toBe('v4');
    });
  });

  describe('across tabs', () => {
    it('shares one cap between tabs when Web Locks exist', async () => {
      /*
        Given two tabs with Web Locks
        When each tab requests thumbnails of two videos
        Then only three requests are sent in total
        When one of them finishes
        Then the fourth is sent
      */
      setUp(true);
      const [tabA, tabB] = [openTab(), openTab()];

      requestThumbnail('a1', tabA);
      requestThumbnail('a2', tabA);
      requestThumbnail('b1', tabB);
      requestThumbnail('b2', tabB);

      await expectRequests({ sent: 3 });
      finish(sent[0]);
      await expectRequests({ sent: 4 });
    });

    it('caps each tab on its own when Web Locks are missing', async () => {
      /*
        Given two tabs without Web Locks
        When each tab requests thumbnails of three videos
        Then all six requests are sent
      */
      setUp(false);
      const [tabA, tabB] = [openTab(), openTab()];

      ['a1', 'a2', 'a3'].forEach(id => requestThumbnail(id, tabA));
      ['b1', 'b2', 'b3'].forEach(id => requestThumbnail(id, tabB));

      await expectRequests({ sent: 6 });
    });
  });
});
