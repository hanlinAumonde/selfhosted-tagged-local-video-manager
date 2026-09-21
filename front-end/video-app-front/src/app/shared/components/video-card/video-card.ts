import { Component, computed, effect, inject, input, signal, ChangeDetectionStrategy } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { SearchedVideo } from '../../models/GQL-result.model';
import { HttpClientService } from '../../../services/Http-client-service/Http-client.service';

@Component({
  selector: 'app-video-card',
  imports: [RouterLink, MatCardModule, MatChipsModule, MatIconModule, MatTooltipModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './video-card.html',
})
export class VideoCard {
  video = input<SearchedVideo | null>(null);

  private httpClientService = inject(HttpClientService);

  readonly defaultThumbnail = '/videoicon.png';

  thumbnailSrc = signal(this.defaultThumbnail);
  isDefaultThumbnail = signal(true);

  /** A video held by a migration task cannot be opened until the task settles. */
  isLocked = computed(() => this.video()?.isLocked ?? false);

  formattedDuration = computed(() => {
    const totalSeconds = this.video()?.duration ?? 0.0;
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = Math.floor(totalSeconds % 60);
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  });

  views = computed(() => {
    if (!this.video()?.viewCount) return '0';
    // use x, xK, xM format
    const count = this.video()!.viewCount;
    if (count < 1000) return count.toString();
    if (count < 1_000_000) return (count / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
    return (count / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
  });

  constructor() {
    effect(() => {
      const video = this.video();
      if (!video?.id) {
        this.thumbnailSrc.set(this.defaultThumbnail);
        this.isDefaultThumbnail.set(true);
        return;
      }

      this.httpClientService.getThumbnailUrl(video.id)
        .subscribe(response => {
          const blob = response.body;
          if (blob) {
            const url = URL.createObjectURL(blob);
            this.thumbnailSrc.set(url);
            this.isDefaultThumbnail.set(false);
          } else {
            this.thumbnailSrc.set(this.defaultThumbnail);
            this.isDefaultThumbnail.set(true);
          }
        }
      );
    });
  }

  get formattedDate(): string {
    if (!this.video()) return '';
    return new Date(this.video()!.lastModifyTime * 1000).toLocaleDateString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  }
}
