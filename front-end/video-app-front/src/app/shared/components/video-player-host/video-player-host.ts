import {
  Component,
  input,
  output,
  ChangeDetectionStrategy,
  CUSTOM_ELEMENTS_SCHEMA
} from '@angular/core';
// Side-effect imports register <video-player> and <video-skin>. Keeping them here rather than in
// main.ts is what makes the player (and the skin's own styles) load with the deferred chunk.
import '@videojs/html/video/player';
import '@videojs/html/video/skin';

@Component({
  selector: 'app-video-player-host',
  standalone: true,
  templateUrl: './video-player-host.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './video-player-host.css',
  schemas: [CUSTOM_ELEMENTS_SCHEMA],
})
export class VideoPlayerHost {

  src = input<string>('');

  played = output<void>();
}
