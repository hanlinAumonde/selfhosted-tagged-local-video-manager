import { Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatDialogRef, MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatIconModule } from '@angular/material/icon';
import { MatRadioModule } from '@angular/material/radio';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  BatchResultType,
  RelativePathInput,
  SearchField,
  SeriesOperationInput,
  SeriesOrderEntryInput,
  VideosBatchOperationInput
} from '../../../core/graphql/generated/graphql';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { ValidationService } from '../../../services/validation-service/validation.service';
import { debounceTime, distinctUntilChanged, startWith, switchMap, takeWhile } from 'rxjs';
import { ToastService } from '../../../services/toast-service/toast.service';
import { ToastDisplayer } from "../../../shared/components/toast-displayer/toast-displayer";
import { BatchPanelData, BatchPanelVideoItem, SeriesAction, TagDirection } from '../../models/panels.model';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import { ToastType } from '../../models/toast.model';
import { SeriesReorderList } from '../series-reorder-list/series-reorder-list';


@Component({
  selector: 'app-batch-tags-panel',
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatChipsModule,
    MatAutocompleteModule,
    MatIconModule,
    MatRadioModule,
    MatProgressSpinnerModule,
    MatExpansionModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatTooltipModule,
    ToastDisplayer,
    SeriesReorderList,
],
  templateUrl: './batch-operation-panel.html'
})
export class BatchOperationPanel {
  private dialogRef = inject(MatDialogRef<BatchOperationPanel>);
  private data = inject<BatchPanelData>(MAT_DIALOG_DATA);
  private formBuilder = inject(FormBuilder);
  private gqlService = inject(GqlService);
  private validationService = inject(ValidationService);
  private toastService = inject(ToastService);
  private videoUpdateEventService = inject(VideoUpdateEventService);
  private destroyRef = inject(DestroyRef);

  readonly isVideoMode = this.data.mode === 'videos';
  readonly videoIds = this.data.videos ?? new Set<string>();
  readonly directoryPath = this.data.selectedDirectoryPath ?? '';
  
  form = this.formBuilder.group({
    authorInput: ['', [this.validationService.authorValidator()]],
    addTagInput: ['', [this.validationService.tagValidator()]],
    removeTagInput: ['', [this.validationService.tagValidator()]],
    modifySeries: [false],
    seriesAction: ['set' as SeriesAction],
    seriesName: ['', [this.validationService.seriesNameValidator()]],
  });

  get authorInput() { return this.form.get('authorInput') as FormControl<string>; }
  get addTagInput() { return this.form.get('addTagInput') as FormControl<string>; }
  get removeTagInput() { return this.form.get('removeTagInput') as FormControl<string>; }
  get seriesNameInput() { return this.form.get('seriesName') as FormControl<string>; }

  newAuthor = toSignal(
    this.authorInput.valueChanges.pipe(startWith(this.authorInput.value)),
    { initialValue: '' }
  );

  newSeriesName = toSignal(
    this.seriesNameInput.valueChanges.pipe(startWith(this.seriesNameInput.value)),
    { initialValue: '' }
  );

  modifySeries = toSignal(
    this.form.controls.modifySeries.valueChanges.pipe(startWith(this.form.controls.modifySeries.value)),
    { initialValue: false }
  );

  seriesAction = toSignal(
    this.form.controls.seriesAction.valueChanges.pipe(startWith(this.form.controls.seriesAction.value)),
    { initialValue: 'set' as SeriesAction }
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
    if (!this.modifySeries()) return null;
    if (this.seriesAction() !== 'set') return null;
    const target = (this.newSeriesName() ?? '').trim();
    if (!target) return null;
    const existing = this.existingSeriesNames().filter(n => n !== target);
    if (existing.length === 0) return null;
    if (existing.length === 1) {
      return `Selected videos currently belong to series "${existing[0]}". Saving will move them into "${target}".`;
    }
    return `Selected videos currently span ${existing.length} series (${existing.join(', ')}). Saving will move them all into "${target}".`;
  });

  addTags = signal<string[]>([]);
  removeTags = signal<string[]>([]);
  isSaving = signal<boolean>(false);

  // Ordered videos for series reordering. Initial order: by existing seriesOrder asc, then by name.
  orderedVideos = signal<BatchPanelVideoItem[]>(
    [...(this.data.videoItems ?? [])].sort((a, b) => {
      const aHas = a.seriesOrder !== null && a.seriesOrder !== undefined;
      const bHas = b.seriesOrder !== null && b.seriesOrder !== undefined;
      if (aHas && bHas) return (a.seriesOrder as number) - (b.seriesOrder as number);
      if (aHas) return -1;
      if (bHas) return 1;
      return a.name.localeCompare(b.name);
    })
  );

  authorSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(this.authorInput.valueChanges, SearchField.Author),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  addTagSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(
      this.addTagInput.valueChanges.pipe(startWith(this.addTagInput.value)),
      SearchField.Tag
    ),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  removeTagSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(
      this.removeTagInput.valueChanges.pipe(startWith(this.removeTagInput.value)),
      SearchField.Tag
    ),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  seriesSuggestions = toSignal(
    this.seriesNameInput.valueChanges.pipe(
      startWith(this.seriesNameInput.value),
      debounceTime(300),
      distinctUntilChanged(),
      switchMap(value => this.gqlService.searchSeriesByPrefixQuery(value ?? '', 10))
    ),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  tagsError = computed(() => {
    for (const list of [this.addTags(), this.removeTags()]) {
      const result = this.validationService.validateTagsArray(list);
      if (!result.valid) return result.error;
    }
    return null;
  });

  hasSeriesOperation = computed(() => {
    if (!this.isVideoMode) return false;
    if (!this.modifySeries()) return false;
    const action = this.seriesAction();
    if (action === 'clear') return true;
    return (this.newSeriesName() ?? '').trim() !== '';
  });

  processingMessage = signal<string>('');

  private tagList(direction: TagDirection) {
    return direction === 'add' ? this.addTags : this.removeTags;
  }

  private clearTagInput(direction: TagDirection) {
    if (direction === 'add') this.form.patchValue({ addTagInput: '' });
    else this.form.patchValue({ removeTagInput: '' });
  }

  /** A tag already claimed by the other direction, which the backend would refuse. */
  conflictingTag = signal<string | null>(null);

  addTag(direction: TagDirection, tagValue?: string) {
    const value = tagValue ?? (
      direction === 'add' ? this.addTagInput.value : this.removeTagInput.value
    );

    if (!value || value.trim() === '') {
      return;
    }

    const trimmedTag = value.trim();

    const tagValidation = this.validationService.validateTag(trimmedTag);
    if (!tagValidation.valid) {
      return;
    }

    // The same tag in both lists says nothing about what should happen to it, so the
    // backend rejects the request outright. Saying so here costs a round trip less.
    const other = direction === 'add' ? this.removeTags() : this.addTags();
    if (other.includes(trimmedTag)) {
      this.conflictingTag.set(trimmedTag);
      return;
    }

    const list = this.tagList(direction);
    const tagsArrayValidation = this.validationService.validateTagsArray([...list(), trimmedTag]);
    if (!tagsArrayValidation.valid) {
      return;
    }

    this.conflictingTag.set(null);
    if (!list().includes(trimmedTag)) {
      list.update(tags => [...tags, trimmedTag]);
    }
    this.clearTagInput(direction);
  }

  selectAuthorSuggestion(author: string) {
    this.form.patchValue({ authorInput: author });
  }

  selectTagSuggestion(direction: TagDirection, tag: string) {
    this.addTag(direction, tag);
  }

  selectSeriesSuggestion(name: string) {
    this.form.patchValue({ seriesName: name });
  }

  removeTag(direction: TagDirection, tag: string) {
    this.tagList(direction).update(tags => tags.filter(t => t !== tag));
    if (this.conflictingTag() === tag) this.conflictingTag.set(null);
  }

  onTagInputEnter(direction: TagDirection, event: Event) {
    event.preventDefault();
    this.addTag(direction);
  }

  private buildSeriesOperation(): SeriesOperationInput | undefined {
    if (!this.isVideoMode) return undefined;
    if (!this.modifySeries()) return undefined;
    const action = this.seriesAction();
    if (action === 'clear') {
      return { clear: true };
    }
    const name = (this.newSeriesName() ?? '').trim();
    if (!name) return undefined;
    const orders: SeriesOrderEntryInput[] = this.orderedVideos().map((item, index) => ({
      videoId: item.id,
      order: index + 1,
    }));
    return { clear: false, name, orders };
  }

  handleSave() {
    const seriesOperation = this.buildSeriesOperation();
    const hasTags = this.addTags().length > 0 || this.removeTags().length > 0;
    const hasAuthor = (this.newAuthor() ?? '').trim() !== '';

    if (this.isVideoMode && !hasTags && !hasAuthor && !seriesOperation) return;
    if (this.form.invalid || this.tagsError()) return;
    this.isSaving.set(true);

    const tagsOperation = hasTags ? {
      addTags: this.addTags(),
      removeTags: this.removeTags()
    } : undefined;

    const author = hasAuthor
      ? (this.form.value.authorInput ?? '').trim()
      : undefined;

    const relativePath: RelativePathInput = this.isVideoMode ? {} : { relativePath: this.directoryPath };
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
        if(result.data?.result?.resultType === undefined && result.data?.status){
          this.processingMessage.set(result.data.status);
        }else if(result.data?.result?.resultType){
          this.isSaving.set(false);
          this.processingMessage.set('');
          const resultType = result.data.result.resultType;
          switch(resultType) {
            case BatchResultType.Success:
            case BatchResultType.PartialSuccess:
              this.videoUpdateEventService.emitUpdated(Array.from(this.videoIds));
              if(resultType === BatchResultType.PartialSuccess){
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
          this.toastService.emitNewToast(
            'Batch update failed. Please try again.',
            ToastType.Error
          );
          this.processingMessage.set('');
        }
      },
      error: (err) => {
        this.isSaving.set(false);
        this.toastService.emitNewToast(
          'Error performing batch update: ' + err.message,
          ToastType.Error
        );
      }
    });
  }

  isInvalid = computed(() => {
    if (this.form.invalid || this.tagsError()) return true;
    if (!this.isVideoMode) return false;
    const hasAny =
      this.addTags().length > 0 ||
      this.removeTags().length > 0 ||
      (this.newAuthor() ?? '').trim() !== '' ||
      this.hasSeriesOperation();
    return !hasAny;
  });

  handleCancel() {
    this.dialogRef.close();
  }
}
