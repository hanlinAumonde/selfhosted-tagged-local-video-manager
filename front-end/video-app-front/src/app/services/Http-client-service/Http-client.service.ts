import { HttpClient, HttpResponse } from "@angular/common/http";
import { inject, Injectable } from "@angular/core";
import { finalize, Observable, Subscription } from "rxjs";
import { environment } from "../../../environments/environment";

// Browsers open at most 6 HTTP/1.1 connections per origin, shared by every tab, and
// thumbnails share the origin with GraphQL and the video stream. A thumbnail that has
// to be generated holds its connection for seconds, so a screenful of them would leave
// every other request stalled in the browser's own queue. Capping thumbnails well below
// 6 — across all tabs, since the connection pool is shared too — keeps the rest usable.
const THUMBNAIL_SLOTS = 3;

type Release = () => void;

interface ThumbnailSlots {
    /** Resolves once a slot is held; rejects if `signal` aborts while still waiting. */
    acquire(signal: AbortSignal): Promise<Release>;
}

/** One cap for every tab of this origin, kept by the browser's lock manager. */
class CrossTabSlots implements ThumbnailSlots {
    private nextSlot = 0;

    constructor(private locks: LockManager) {}

    async acquire(signal: AbortSignal): Promise<Release> {
        for (let i = 0; i < THUMBNAIL_SLOTS; i++) {
            const release = await this.hold(slotName(i), { ifAvailable: true });
            if (release) return release;
        }
        signal.throwIfAborted();
        // All taken: queue on one slot. Rotating keeps one busy slot from collecting
        // every waiter while the others free up.
        const release = await this.hold(slotName(this.nextSlot++ % THUMBNAIL_SLOTS), { signal });
        return release!;
    }

    /** A lock is held until its callback's promise settles, so that promise is the release. */
    private hold(name: string, options: LockOptions): Promise<Release | null> {
        return new Promise((resolve, reject) => {
            this.locks.request(name, options, (lock): Promise<void> | undefined => {
                if (!lock) {
                    resolve(null);
                    return undefined;
                }
                return new Promise<void>(release => resolve(() => release()));
            }).catch(reject);
        });
    }
}

/**
 * Web Locks exist only in secure contexts: an app served over plain HTTP from a LAN
 * address has none. The cap then holds per tab, which is still far better than none.
 */
class TabSlots implements ThumbnailSlots {
    private active = 0;
    private waiting: (() => void)[] = [];

    acquire(signal: AbortSignal): Promise<Release> {
        return new Promise((resolve, reject) => {
            const grant = () => {
                this.active++;
                let released = false;
                resolve(() => {
                    if (released) return;
                    released = true;
                    this.active--;
                    this.waiting.shift()?.();
                });
            };

            if (this.active < THUMBNAIL_SLOTS) {
                grant();
                return;
            }
            this.waiting.push(grant);
            signal.addEventListener("abort", () => {
                this.waiting = this.waiting.filter(waiting => waiting !== grant);
                reject(signal.reason);
            }, { once: true });
        });
    }
}

function slotName(index: number): string {
    return `video-app:thumbnail-slot-${index}`;
}

@Injectable({
  providedIn: "root",
})
export class HttpClientService {
    private httpClient = inject(HttpClient);
    private thumbnailSlots: ThumbnailSlots = typeof navigator !== "undefined" && navigator.locks
        ? new CrossTabSlots(navigator.locks)
        : new TabSlots();

    getThumbnailUrl(videoId: string): Observable<HttpResponse<Blob>> {
        const request$ = this.httpClient.get(environment.backend_api + environment.videopage_thumbnail_api, {
            responseType: 'blob',
            observe: 'response',
            params: {
                video_id: videoId
            },
            withCredentials: false
        });

        return new Observable<HttpResponse<Blob>>(subscriber => {
            const abort = new AbortController();
            let running: Subscription | undefined;
            let closed = false;

            this.thumbnailSlots.acquire(abort.signal).then(
                release => {
                    if (closed) {
                        // Unsubscribed in the moment the slot was granted: hand it straight back.
                        release();
                        return;
                    }
                    running = request$.pipe(finalize(release)).subscribe(subscriber);
                },
                error => {
                    // An abort is our own unsubscribe; nobody is listening for it.
                    if (!closed) subscriber.error(error);
                }
            );

            return () => {
                closed = true;
                abort.abort();
                running?.unsubscribe();
            };
        });
    }
}
