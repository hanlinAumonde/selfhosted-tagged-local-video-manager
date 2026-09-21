import {
  AfterViewInit,
  Component,
  effect,
  ElementRef,
  inject,
  input,
  signal,
  viewChildren,
  ChangeDetectionStrategy
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { HttpClientService } from '../../../services/Http-client-service/Http-client.service';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import { ResultState, SeriesVideosDetail } from '../../models/GQL-result.model';
import { VideoUpdateEvent } from '../../models/events.model';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-series-panel',
  imports: [RouterLink, MatIconModule, MatProgressSpinnerModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './series-panel.html',
})
export class SeriesPanel implements AfterViewInit {
  private gqlService = inject(GqlService);
  private httpClientService = inject(HttpClientService);
  private videoUpdateEventService = inject(VideoUpdateEventService);

  seriesName = input.required<string | null | undefined>();
  currentVideoId = input.required<string | null | undefined>();

  readonly defaultThumbnail = '/videoicon.png';

  seriesVideos = signal<ResultState<SeriesVideosDetail>>(
    this.gqlService.initialSignalData<SeriesVideosDetail>([])
  );

  private thumbnailCache = new Map<string, string>();
  thumbnailSrcById = signal<Record<string, string>>({});

  itemRefs = viewChildren<ElementRef<HTMLLIElement>>('itemRef');

  private reloadToken = signal(0);
  private loadedSeriesName: string | null = null;

  constructor() {
    effect((onCleanup) => {
      const name = this.seriesName();
      this.reloadToken();
      if (!name) {
        this.loadedSeriesName = null;
        this.seriesVideos.set(this.gqlService.initialSignalData<SeriesVideosDetail>([]));
        return;
      }

      const isRefresh = name === this.loadedSeriesName;
      this.loadedSeriesName = name;

      const sub = this.gqlService.getSeriesVideosQuery(name).subscribe(result => {
        this.seriesVideos.update(previous => ({
          loading: result.loading && !isRefresh,
          error: result.error,
          data: result.data ?? (isRefresh ? previous.data : null),
        }));
        if (!result.loading && result.data) {
          this.loadThumbnails(result.data);
        }
      });
      onCleanup(() => sub.unsubscribe());
    });

    effect(() => {
      // scroll current into view when the list or current id changes
      const currentId = this.currentVideoId();
      const videos = this.seriesVideos().data;
      const refs = this.itemRefs();
      if (!currentId || !videos || refs.length === 0) return;
      queueMicrotask(() => this.scrollCurrentIntoView());
    });

    this.videoUpdateEventService.onEvent()
      .pipe(takeUntilDestroyed())
      .subscribe(event => {
        if (this.isAffected(event)) {
          this.reloadToken.update(token => token + 1);
        }
      });
  }

  ngAfterViewInit() {
    this.scrollCurrentIntoView();
  }

  private isAffected(event: VideoUpdateEvent): boolean {
    if (event.videoIds.length === 0) return false;
    const touched = new Set(event.videoIds);
    const currentId = this.currentVideoId();
    if (currentId && touched.has(currentId)) return true;
    return (this.seriesVideos().data ?? []).some(video => touched.has(video.id));
  }

  private scrollCurrentIntoView() {
    const currentId = this.currentVideoId();
    const videos = this.seriesVideos().data;
    const refs = this.itemRefs();
    if (!currentId || !videos || refs.length === 0) return;
    const index = videos.findIndex(v => v.id === currentId);
    if (index < 0 || index >= refs.length) return;
    refs[index].nativeElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  private loadThumbnails(videos: SeriesVideosDetail) {
    for (const v of videos) {
      if (this.thumbnailCache.has(v.id)) continue;
      this.thumbnailCache.set(v.id, this.defaultThumbnail);
      this.httpClientService.getThumbnailUrl(v.id).subscribe({
        next: (response) => {
          const blob = response.body;
          if (blob) {
            const url = URL.createObjectURL(blob);
            this.thumbnailCache.set(v.id, url);
            this.thumbnailSrcById.update(current => ({ ...current, [v.id]: url }));
          }
        }
      });
    }
  }

  thumbnailFor(videoId: string): string {
    return this.thumbnailSrcById()[videoId] ?? this.defaultThumbnail;
  }

  formatDuration(seconds: number | null | undefined): string {
    const total = seconds ?? 0;
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  linkToVideo(videoId: string): string[] {
    return [environment.videopage_api, videoId];
  }
}
