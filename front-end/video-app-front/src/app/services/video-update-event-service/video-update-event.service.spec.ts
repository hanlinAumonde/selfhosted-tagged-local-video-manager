import { TestBed } from '@angular/core/testing';
import { Observable } from 'rxjs';

import { VideoUpdateEventService } from './video-update-event.service';
import { VideoUpdateEvent, VideoUpdateType } from '../../shared/models/events.model';
import { environment } from '../../../environments/environment';

const { Updated, Deleted, Migrated } = VideoUpdateType;

/** Everything a stream emits, and whether it has completed. */
function record(stream: Observable<VideoUpdateEvent>) {
  const recorded = { events: [] as VideoUpdateEvent[], completed: false };
  stream.subscribe({
    next: event => recorded.events.push(event),
    complete: () => (recorded.completed = true),
  });
  return recorded;
}

describe('VideoUpdateEventService', () => {
  let service: VideoUpdateEventService;
  let otherTabs: BroadcastChannel[];

  /** A channel with the app's name, standing in for another open tab. */
  function openOtherTab() {
    const channel = new BroadcastChannel(environment.videoUpdateChannel);
    otherTabs.push(channel);
    const received: VideoUpdateEvent[] = [];
    channel.onmessage = (e: MessageEvent<VideoUpdateEvent>) => received.push(e.data);
    return { channel, received };
  }

  const sentinel: VideoUpdateEvent = { type: Updated, videoIds: ['sentinel'] };

  beforeEach(() => {
    otherTabs = [];
    TestBed.configureTestingModule({});
    service = TestBed.inject(VideoUpdateEventService);
  });

  afterEach(() => otherTabs.forEach(channel => channel.close()));

  describe('broadcast events', () => {
    it('delivers an update to this tab and to other tabs', async () => {
      /*
        Given this tab listens on onEvent(), onUpdated() and onDeleted()
        And another tab listens on the video update channel
        When emitUpdated() is called with videos "v1" and "v2"
        Then onEvent() and onUpdated() receive an Updated event for "v1" and "v2"
        And onDeleted() receives nothing
        And the other tab receives the same Updated event
      */
      const all = record(service.onEvent());
      const updated = record(service.onUpdated());
      const deleted = record(service.onDeleted());
      const otherTab = openOtherTab();

      service.emitUpdated(['v1', 'v2']);

      const expected = { type: Updated, videoIds: ['v1', 'v2'] };
      expect(all.events).toEqual([expected]);
      expect(updated.events).toEqual([expected]);
      expect(deleted.events).toEqual([]);
      await vi.waitFor(() => expect(otherTab.received).toEqual([expected]));
    });

    it('delivers deleted videos and a deleted directory as Deleted events', async () => {
      /*
        Given this tab listens on onDeleted() and onUpdated()
        And another tab listens on the video update channel
        When emitVideosDeleted() is called with videos "v1" and "v2"
        And emitDirectoryDeleted() is called with directory "local/a"
        Then onDeleted() receives a Deleted event for "v1" and "v2"
        And then a Deleted event with no videos and directory "local/a"
        And onUpdated() receives nothing
        And the other tab receives both events in the same order
      */
      const deleted = record(service.onDeleted());
      const updated = record(service.onUpdated());
      const otherTab = openOtherTab();

      service.emitVideosDeleted(['v1', 'v2']);
      service.emitDirectoryDeleted('local/a');

      const expected = [
        { type: Deleted, videoIds: ['v1', 'v2'] },
        { type: Deleted, videoIds: [], directoryPath: 'local/a' },
      ];
      expect(deleted.events).toEqual(expected);
      expect(updated.events).toEqual([]);
      await vi.waitFor(() => expect(otherTab.received).toEqual(expected));
    });

    it('passes events from another tab to the broadcast streams but not the local one', async () => {
      /*
        Given this tab listens on onEvent(), onUpdated() and onLocalEvent()
        When another tab posts an Updated event for "v1" on the video update channel
        Then onEvent() and onUpdated() receive that event
        And onLocalEvent() receives nothing
      */
      const all = record(service.onEvent());
      const updated = record(service.onUpdated());
      const local = record(service.onLocalEvent());
      const otherTab = openOtherTab();

      const event = { type: Updated, videoIds: ['v1'] };
      otherTab.channel.postMessage(event);

      await vi.waitFor(() => expect(all.events).toEqual([event]));
      expect(updated.events).toEqual([event]);
      expect(local.events).toEqual([]);
    });
  });

  describe('local events', () => {
    it('keeps a migration inside this tab', async () => {
      /*
        Given this tab listens on onEvent() and onLocalEvent()
        And another tab listens on the video update channel
        When emitMigrated() is called for source "local/a" and target "local/b"
        Then onLocalEvent() receives a Migrated event with no videos,
          directory "local/a" and target directory "local/b"
        And onEvent() receives nothing
        And the other tab receives nothing
      */
      const all = record(service.onEvent());
      const local = record(service.onLocalEvent());
      const otherTab = openOtherTab();

      service.emitMigrated('local/a', 'local/b');

      expect(local.events).toEqual([
        { type: Migrated, videoIds: [], directoryPath: 'local/a', targetDirectoryPath: 'local/b' },
      ]);
      expect(all.events).toEqual([]);
      // Channel messages arrive in order, so once a later broadcast has landed,
      // anything the migration had posted would have landed before it.
      service.emit(sentinel);
      await vi.waitFor(() => expect(otherTab.received).toEqual([sentinel]));
    });
  });

  describe('ngOnDestroy', () => {
    it('stops listening to other tabs and completes every stream', async () => {
      /*
        Given this tab listens on onEvent() and onLocalEvent()
        When the service is destroyed
        Then both streams complete
        And an event posted afterwards by another tab is not delivered
      */
      const all = record(service.onEvent());
      const local = record(service.onLocalEvent());
      const otherTab = openOtherTab();
      const witness = openOtherTab();

      service.ngOnDestroy();

      expect(all.completed).toBe(true);
      expect(local.completed).toBe(true);
      otherTab.channel.postMessage(sentinel);
      await vi.waitFor(() => expect(witness.received).toEqual([sentinel]));
      expect(all.events).toEqual([]);
    });
  });
});
