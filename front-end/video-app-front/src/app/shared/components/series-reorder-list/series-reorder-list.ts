import { Component, computed, input, output, ChangeDetectionStrategy } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { BatchPanelVideoItem } from '../../models/panels.model';

@Component({
  selector: 'app-series-reorder-list',
  imports: [MatButtonModule, MatIconModule, MatTooltipModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './series-reorder-list.html',
})
export class SeriesReorderList {
  items = input.required<ReadonlyArray<BatchPanelVideoItem>>();
  // When set, only the row whose id matches can be moved via arrow buttons.
  // When null/undefined, every row is movable.
  movableId = input<string | null | undefined>(null);
  emptyHint = input<string>('No videos in this series yet.');

  itemsChange = output<BatchPanelVideoItem[]>();

  readonly length = computed(() => this.items().length);

  canMoveUp(index: number): boolean {
    if (index <= 0) return false;
    const movable = this.movableId();
    if (!movable) return true;
    return this.items()[index]?.id === movable;
  }

  canMoveDown(index: number): boolean {
    if (index < 0 || index >= this.length() - 1) return false;
    const movable = this.movableId();
    if (!movable) return true;
    return this.items()[index]?.id === movable;
  }

  moveUp(index: number) {
    if (!this.canMoveUp(index)) return;
    const next = [...this.items()];
    [next[index - 1], next[index]] = [next[index], next[index - 1]];
    this.itemsChange.emit(next);
  }

  moveDown(index: number) {
    if (!this.canMoveDown(index)) return;
    const next = [...this.items()];
    [next[index], next[index + 1]] = [next[index + 1], next[index]];
    this.itemsChange.emit(next);
  }

  showVideoTitle(videoId: string, videoName: string): string{
    return videoId == this.movableId() ? 'Current Video' : videoName;
  }
}
