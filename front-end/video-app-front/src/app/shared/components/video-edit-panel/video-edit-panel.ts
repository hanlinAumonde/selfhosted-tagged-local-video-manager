import { Component, signal, computed, effect, inject, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { apply, form, FormField, required, submit } from '@angular/forms/signals';
import { MatDialogRef, MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatRadioModule } from '@angular/material/radio';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { SearchField, SeriesFieldInput, SeriesOrderEntryInput } from '../../../core/graphql/generated/graphql';
import {
  VideoEditPanelMode,
  VideoEditPanelData,
  EditableVideo,
  BatchPanelVideoItem,
  SeriesEdit,
} from '../../models/panels.model';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { VideoMutationDetail, SeriesVideosDetail } from '../../models/GQL-result.model';
import { maxLengthRule, seriesEditSchema, tagListRule } from '../../../services/validation-service/validation.rules';
import { ToastService } from '../../../services/toast-service/toast.service';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import { ToastDisplayer } from "../toast-displayer/toast-displayer";
import { ToastType } from '../../models/toast.model';
import { SeriesNameInput } from '../series-name-input/series-name-input';
import { SeriesReorderList } from '../series-reorder-list/series-reorder-list';
import { TagChipInput } from '../tag-chip-input/tag-chip-input';

@Component({
  selector: 'app-video-edit-panel',
  imports: [
    FormField,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatAutocompleteModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatRadioModule,
    MatSlideToggleModule,
    ToastDisplayer,
    SeriesNameInput,
    SeriesReorderList,
    TagChipInput,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './video-edit-panel.html'
})
export class VideoEditPanel {
  private dialogRef: MatDialogRef<VideoEditPanel, string[] | VideoMutationDetail> = inject(MatDialogRef);
  private data = inject<VideoEditPanelData>(MAT_DIALOG_DATA);
  private gqlService = inject(GqlService);
  private toastService = inject(ToastService);
  private videoUpdateEventService = inject(VideoUpdateEventService);
  private destroyRef = inject(DestroyRef);

  mode: VideoEditPanelMode = this.data.mode;
  video = signal<EditableVideo | undefined>(this.data.video);

  protected model = signal({
    name: this.data.video?.name ?? '',
    author: this.data.video?.author ?? '',
    loved: this.data.video?.loved ?? false,
    introduction: this.data.video?.introduction ?? '',
    tags: this.data.mode === 'full'
      ? (this.data.video?.tags.map(tag => tag.name) ?? [])
      : [...(this.data.selectedTags ?? [])],
    series: {
      modify: false,
      action: 'set',
      name: this.data.video?.seriesName ?? '',
      members: [],
    } as SeriesEdit,
  });

  editForm = form(
    this.model,
    path => {
      apply(path.tags, tagListRule);
      // Filter mode collects tags and nothing else; the other fields are not even rendered.
      if (this.mode !== 'full') return;
      required(path.name, { message: 'Title is required' });
      maxLengthRule(path.name, environment.VALIDATION_RULES.NAME_MAX_LENGTH);
      maxLengthRule(path.author, environment.VALIDATION_RULES.AUTHOR_MAX_LENGTH);
      maxLengthRule(path.introduction, environment.VALIDATION_RULES.INTRODUCTION_MAX_LENGTH);
      apply(path.series, seriesEditSchema);
    },
    { submission: { action: () => this.save() } },
  );

  /*
    Most recently confirmed series name: either the original name on check-in, or the last
    autocomplete suggestion the user picked. Typing into the input without picking a
    suggestion does not update this, so we can detect "user typed something new" and reset
    the list to just the current video.
  */
  private committedSeriesName = signal<string | null>(null);
  isLoadingSeriesMembers = signal<boolean>(false);

  currentVideoId = computed(() => this.video()?.id ?? null);

  authorSuggestions = this.mode === 'full'
    ? toSignal(
        this.gqlService.getSuggestionsQuery(
          toObservable(computed(() => this.model().author)),
          SearchField.Author
        ),
        { initialValue: this.gqlService.initialSignalData<string[]>([]) }
      )
    : signal(this.gqlService.initialSignalData<string[]>([]));

  isFullMode = computed(() => this.mode === 'full');

  saveButtonText = computed(() =>
    this.mode === 'filter' ? 'Apply Filter' : (this.editForm().submitting() ? 'Saving...' : 'Save')
  );

  constructor() {
    effect(() => {
      const typed = this.model().series.name;
      const committed = this.committedSeriesName();
      // Only a committed name can be departed from; a blank slate has nothing to reset.
      if (committed === null) return;
      if (typed !== committed) {
        this.committedSeriesName.set(null);
        this.setSeriesMembers([this.currentVideoAsItem()]);
      }
    });
  }

  private setSeriesMembers(members: BatchPanelVideoItem[]) {
    this.model.update(current => ({ ...current, series: { ...current.series, members } }));
  }

  protected onSeriesMembersChange(members: BatchPanelVideoItem[]) {
    this.setSeriesMembers(members);
  }

  onModifySeriesToggle(checked: boolean) {
    if (!checked) {
      // Revert any staged changes.
      this.committedSeriesName.set(null);
      this.model.update(current => ({
        ...current,
        series: {
          ...current.series,
          action: 'set',
          name: this.video()?.seriesName ?? '',
          members: [],
        },
      }));
      return;
    }

    const current = this.video();
    if (!current) return;
    const existingName = current.seriesName ?? '';
    if (existingName) {
      this.committedSeriesName.set(existingName);
      this.loadSeriesMembers(existingName);
    } else {
      this.committedSeriesName.set(null);
      this.setSeriesMembers([this.currentVideoAsItem()]);
    }
  }

  protected onSeriesSuggestionPicked(name: string) {
    this.committedSeriesName.set(name);
    this.loadSeriesMembers(name);
  }

  protected toggleLoved() {
    this.model.update(current => ({ ...current, loved: !current.loved }));
  }

  protected selectAuthorSuggestion(author: string) {
    this.model.update(current => ({ ...current, author }));
  }

  private currentVideoAsItem(): BatchPanelVideoItem {
    const v = this.video()!;
    return {
      id: v.id,
      name: v.name,
      seriesName: v.seriesName ?? null,
      seriesOrder: v.seriesOrder ?? null,
    };
  }

  private loadSeriesMembers(name: string) {
    this.isLoadingSeriesMembers.set(true);
    this.gqlService.getSeriesVideosQuery(name)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          if (result.loading) return;
          this.isLoadingSeriesMembers.set(false);
          const fetched = (result.data ?? []) as SeriesVideosDetail;
          const currentItem = this.currentVideoAsItem();

          const sorted = [...fetched].sort((a, b) => {
            const ao = a.seriesOrder ?? Number.POSITIVE_INFINITY;
            const bo = b.seriesOrder ?? Number.POSITIVE_INFINITY;
            if (ao !== bo) return ao - bo;
            return a.name.localeCompare(b.name);
          });
          const mapped: BatchPanelVideoItem[] = sorted.map(v => ({
            id: v.id,
            name: v.name,
            seriesName: name,
            seriesOrder: v.seriesOrder ?? null,
          }));
          // Ensure the current video is in the list (append if missing).
          if (!mapped.some(m => m.id === currentItem.id)) {
            mapped.push(currentItem);
          }
          this.setSeriesMembers(mapped);
        },
        error: () => {
          this.isLoadingSeriesMembers.set(false);
          this.setSeriesMembers([this.currentVideoAsItem()]);
        },
      });
  }

  private buildSeriesInput(): SeriesFieldInput | undefined {
    const series = this.model().series;
    if (!series.modify) return undefined;
    if (series.action === 'clear') return { clear: true };

    const name = series.name.trim();
    if (!name) return { clear: true };

    const orders: SeriesOrderEntryInput[] = series.members.map((item, index) => ({
      videoId: item.id,
      order: index + 1,
    }));
    if (orders.length === 0) {
      // include the current video itself.
      orders.push({ videoId: this.video()!.id, order: 1 });
    }
    return { clear: false, name, orders };
  }

  private affectedVideoIds(seriesInput: SeriesFieldInput | undefined): string[] {
    const ids = new Set<string>([this.video()!.id]);
    for (const entry of seriesInput?.orders ?? []) {
      ids.add(entry.videoId);
    }
    return Array.from(ids);
  }

  handleSave() {
    if (this.editForm().submitting()) return;
    submit(this.editForm);
  }

  private async save(): Promise<null> {
    const draft = this.model();

    if (this.mode === 'filter') {
      this.dialogRef.close(draft.tags);
      return null;
    }
    if (!this.video()) return null;

    const seriesInput = this.buildSeriesInput();

    try {
      const result = await firstValueFrom(
        this.gqlService.updateVideoMetadataMutation(
          this.video()!.id,
          draft.loved,
          draft.tags,
          draft.name,
          draft.introduction,
          draft.author || 'Unknown',
          seriesInput,
        ).pipe(takeUntilDestroyed(this.destroyRef)),
        { defaultValue: null },
      );

      // The dialog was destroyed before the mutation answered; nothing left to report to.
      if (result === null) return null;

      if (result.data?.success) {
        this.videoUpdateEventService.emitUpdated(this.affectedVideoIds(seriesInput));
        this.toastService.emitNewToast('Video information updated successfully.', ToastType.Success);
        this.dialogRef.close(result.data);
      } else {
        // update failed, keep the dialog open for user to retry
        this.toastService.emitNewToast('Failed to update video metadata.', ToastType.Error);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      this.toastService.emitNewToast('Error updating video metadata: ' + message, ToastType.Error);
    }

    return null;
  }

  handleCancel() {
    this.dialogRef.close();
  }
}
