import { Component, computed, DestroyRef, effect, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { apply, form, FormField, submit } from '@angular/forms/signals';
import { MatDialogRef, MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatIconModule } from '@angular/material/icon';
import { MatRadioModule } from '@angular/material/radio';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import { takeWhile } from 'rxjs';
import { environment } from '../../../../environments/environment';
import {
  BatchResultType,
  RelativePathInput,
  SearchField,
  SeriesOperationInput,
  SeriesOrderEntryInput,
  VideosBatchOperationInput
} from '../../../core/graphql/generated/graphql';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { maxLengthRule, seriesEditSchema, tagListRule } from '../../../services/validation-service/validation.rules';
import { ToastService } from '../../../services/toast-service/toast.service';
import { ToastDisplayer } from "../../../shared/components/toast-displayer/toast-displayer";
import { BatchPanelData, BatchPanelVideoItem, SeriesEdit } from '../../models/panels.model';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import { ToastType } from '../../models/toast.model';
import { SeriesNameInput } from '../series-name-input/series-name-input';
import { SeriesReorderList } from '../series-reorder-list/series-reorder-list';
import { TagChipInput } from '../tag-chip-input/tag-chip-input';


@Component({
  selector: 'app-batch-tags-panel',
  imports: [
    FormField,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatAutocompleteModule,
    MatIconModule,
    MatRadioModule,
    MatProgressSpinnerModule,
    MatExpansionModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatTooltipModule,
    ToastDisplayer,
    SeriesNameInput,
    SeriesReorderList,
    TagChipInput,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './batch-operation-panel.html'
})
export class BatchOperationPanel {
  private dialogRef = inject(MatDialogRef<BatchOperationPanel>);
  private data = inject<BatchPanelData>(MAT_DIALOG_DATA);
  private gqlService = inject(GqlService);
  private toastService = inject(ToastService);
  private videoUpdateEventService = inject(VideoUpdateEventService);
  private destroyRef = inject(DestroyRef);

  readonly isVideoMode = this.data.mode === 'videos';
  readonly videoIds = this.data.videos ?? new Set<string>();
  readonly directoryPath = this.data.selectedDirectoryPath ?? '';

  protected model = signal({
    author: '',
    addTags: [] as string[],
    removeTags: [] as string[],
    series: {
      modify: false,
      action: 'set',
      name: '',
      // Initial order: by existing seriesOrder ascending, then by name.
      members: [...(this.data.videoItems ?? [])].sort((a, b) => {
        const aHas = a.seriesOrder !== null && a.seriesOrder !== undefined;
        const bHas = b.seriesOrder !== null && b.seriesOrder !== undefined;
        if (aHas && bHas) return (a.seriesOrder as number) - (b.seriesOrder as number);
        if (aHas) return -1;
        if (bHas) return 1;
        return a.name.localeCompare(b.name);
      }),
    } as SeriesEdit,
  });

  batchForm = form(
    this.model,
    path => {
      maxLengthRule(path.author, environment.VALIDATION_RULES.AUTHOR_MAX_LENGTH);
      apply(path.addTags, tagListRule);
      apply(path.removeTags, tagListRule);
      apply(path.series, seriesEditSchema);
    },
    { submission: { action: () => this.save() } },
  );

  /** A tag already claimed by the other direction, which the backend would refuse. */
  conflictingTag = signal<string | null>(null);

  processingMessage = signal<string>('');

  authorSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(
      toObservable(computed(() => this.model().author)),
      SearchField.Author
    ),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  // Distinct existing series names among the selected videos.
  readonly existingSeriesNames = computed<string[]>(() => {
    const items = this.data.videoItems ?? [];
    const names = new Set<string>();
    for (const item of items) {
      if (item.seriesName) names.add(item.seriesName);
    }
    return Array.from(names).sort();
  });

  // Inline warning: user is reassigning videos that currently live in one or
  // more existing series to a new name. Suppressed when clearing.
  readonly seriesConflictWarning = computed<string | null>(() => {
    if (!this.isVideoMode) return null;
    const series = this.model().series;
    if (!series.modify) return null;
    if (series.action !== 'set') return null;
    const target = series.name.trim();
    if (!target) return null;
    const existing = this.existingSeriesNames().filter(n => n !== target);
    if (existing.length === 0) return null;
    if (existing.length === 1) {
      return `Selected videos currently belong to series "${existing[0]}". Saving will move them into "${target}".`;
    }
    return `Selected videos currently span ${existing.length} series (${existing.join(', ')}). Saving will move them all into "${target}".`;
  });

  hasSeriesOperation = computed(() => {
    if (!this.isVideoMode) return false;
    const series = this.model().series;
    if (!series.modify) return false;
    if (series.action === 'clear') return true;
    return series.name.trim() !== '';
  });

  isInvalid = computed(() => {
    if (this.batchForm().invalid()) return true;
    if (!this.isVideoMode) return false;
    const draft = this.model();
    const hasAny =
      draft.addTags.length > 0 ||
      draft.removeTags.length > 0 ||
      draft.author.trim() !== '' ||
      this.hasSeriesOperation();
    return !hasAny;
  });

  constructor() {
    effect(() => {
      const conflict = this.conflictingTag();
      if (conflict === null) return;
      const draft = this.model();
      // The warning stands only while the tag is still claimed by one of the lists.
      if (!draft.addTags.includes(conflict) && !draft.removeTags.includes(conflict)) {
        this.conflictingTag.set(null);
      }
    });
  }

  protected onSeriesMembersChange(members: BatchPanelVideoItem[]) {
    this.model.update(current => ({ ...current, series: { ...current.series, members } }));
  }

  protected selectAuthorSuggestion(author: string) {
    this.model.update(current => ({ ...current, author }));
  }

  private buildSeriesOperation(): SeriesOperationInput | undefined {
    if (!this.isVideoMode) return undefined;
    const series = this.model().series;
    if (!series.modify) return undefined;
    if (series.action === 'clear') return { clear: true };

    const name = series.name.trim();
    if (!name) return undefined;
    const orders: SeriesOrderEntryInput[] = series.members.map((item, index) => ({
      videoId: item.id,
      order: index + 1,
    }));
    return { clear: false, name, orders };
  }

  handleSave() {
    if (this.batchForm().submitting()) return;
    submit(this.batchForm);
  }

  private save(): Promise<null> {
    const draft = this.model();
    const seriesOperation = this.buildSeriesOperation();
    const hasTags = draft.addTags.length > 0 || draft.removeTags.length > 0;
    const hasAuthor = draft.author.trim() !== '';

    if (this.isVideoMode && !hasTags && !hasAuthor && !seriesOperation) return Promise.resolve(null);

    const tagsOperation = hasTags
      ? { addTags: draft.addTags, removeTags: draft.removeTags }
      : undefined;
    const author = hasAuthor ? draft.author.trim() : undefined;
    const relativePath: RelativePathInput = this.isVideoMode ? {} : { relativePath: this.directoryPath };

    /*
      Unlike the other panels this is a subscription that reports progress before it
      finishes, so it is wrapped rather than awaited directly: the promise settles when the
      stream ends, which is what keeps submitting() true for the whole operation.
    */
    return new Promise<null>(resolve => {
      this.gqlService.batchUpdateVideosSubscription({
        videoIds: Array.from(this.videoIds),
        relativePath: relativePath,
        tagsOperation: tagsOperation,
        author: author,
        seriesOperation: seriesOperation,
      } as VideosBatchOperationInput).pipe(
        takeWhile(result => result.data?.result?.resultType === undefined, true),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: (result) => {
          if (result.data?.result?.resultType === undefined && result.data?.status) {
            this.processingMessage.set(result.data.status);
          } else if (result.data?.result?.resultType) {
            this.processingMessage.set('');
            const resultType = result.data.result.resultType;
            switch (resultType) {
              case BatchResultType.Success:
              case BatchResultType.PartialSuccess:
                this.videoUpdateEventService.emitUpdated(Array.from(this.videoIds));
                if (resultType === BatchResultType.PartialSuccess) {
                  this.toastService.emitNewToast(
                    `Batch update completed with partial success, some videos may not have been updated.
                    \nMessage: ${result.data.result.message ?? 'No additional information provided.'}`,
                    ToastType.Warning
                  );
                } else {
                  this.toastService.emitNewToast('Batch update completed successfully.', ToastType.Success);
                }
                this.dialogRef.close(true);
                break;
              case BatchResultType.AlreadyUpToDate:
                this.toastService.emitNewToast(
                  'All selected videos are already up to date. No changes were made.',
                  ToastType.Warning
                );
                break;
            }
          } else {
            this.toastService.emitNewToast('Batch update failed. Please try again.', ToastType.Error);
            this.processingMessage.set('');
          }
        },
        error: (err) => {
          this.toastService.emitNewToast('Error performing batch update: ' + err.message, ToastType.Error);
          resolve(null);
        },
        complete: () => resolve(null),
      });
    });
  }

  handleCancel() {
    this.dialogRef.close();
  }
}
