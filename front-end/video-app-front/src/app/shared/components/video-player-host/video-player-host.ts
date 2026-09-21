import {
  Component,
  ElementRef,
  OnDestroy,
  effect,
  input,
  output,
  viewChild,
  ChangeDetectionStrategy
} from '@angular/core';
import videojs from 'video.js';
import Player from 'video.js/dist/types/player';

@Component({
  selector: 'app-video-player-host',
  standalone: true,
  templateUrl: './video-player-host.html',
  // Stay transparent to layout: the player sized against the caller's block before
  changeDetection: ChangeDetectionStrategy.Eager,
  styles: `:host { display: block; width: 100%; }`,
})
export class VideoPlayerHost implements OnDestroy {

  src = input<string>('');

  played = output<void>();

  private videoTarget = viewChild<ElementRef<HTMLVideoElement>>('videoTarget');
  private player: Player | null = null;

  constructor() {
    effect(() => {
      const element = this.videoTarget()?.nativeElement;
      const url = this.src();
      if (!element) return;

      const player = this.player ?? this.createPlayer(element);
      if (!url) return;

      // Rewind to the start so a source swap never resumes at the previous offset
      player.pause();
      player.src({ type: 'video/mp4', src: url });
      player.load();
      player.currentTime(0);
    });
  }

  ngOnDestroy() {
    this.player?.dispose();
    this.player = null;
  }

  private createPlayer(element: HTMLVideoElement): Player {
    const player = videojs(element, {
      controls: true,
      autoplay: false,
      preload: 'auto',
      fill: true,
      aspectRatio: '16:9',
      responsive: true,
      playbackRates: [0.5, 1, 1.5, 2],
      controlBar: {
        children: [
          'playToggle',
          'volumePanel',
          'currentTimeDisplay',
          'timeDivider',
          'durationDisplay',
          'progressControl',
          'playbackRateMenuButton',
          'pictureInPictureToggle',
          'fullscreenToggle',
        ],
      },
    });

    player.on('play', () => this.played.emit());

    this.player = player;
    return player;
  }
}
