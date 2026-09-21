import { Component, OnInit, signal, computed, inject, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import {
  FormBuilder,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { MatDialogRef, MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatRadioModule } from '@angular/material/radio';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { debounceTime, distinctUntilChanged, startWith, switchMap } from 'rxjs/operators';
import { SearchField, SeriesFieldInput, SeriesOrderEntryInput } from '../../../core/graphql/generated/graphql';
import {
  VideoEditPanelMode,
  VideoEditPanelData,
  EditableVideo,
  BatchPanelVideoItem,
} from '../../models/panels.model';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { VideoMutationDetail, SeriesVideosDetail } from '../../models/GQL-result.model';
import { ValidationService } from '../../../services/validation-service/validation.service';
import { ToastService } from '../../../services/toast-service/toast.service';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import { ToastDisplayer } from "../toast-displayer/toast-displayer";
import { ToastType } from '../../models/toast.model';
import { SeriesReorderList } from '../series-reorder-list/series-reorder-list';

@Component({
  selector: 'app-video-edit-panel',
  imports: [
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatCheckboxModule,
    MatButtonModule,
    MatChipsModule,
    MatAutocompleteModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatRadioModule,
    MatSlideToggleModule,
    ToastDisplayer,
    SeriesReorderList,
],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './video-edit-panel.html'
})
export class VideoEditPanel implements OnInit {
  private dialogRef: MatDialogRef<VideoEditPanel, string[] | VideoMutationDetail> = inject(MatDialogRef);
  private data = inject<VideoEditPanelData>(MAT_DIALOG_DATA);
  private formBuilder = inject(FormBuilder);
  private gqlService = inject(GqlService);
  private validationService = inject(ValidationService);
  private toastService = inject(ToastService);
  private videoUpdateEventService = inject(VideoUpdateEventService);
  private destroyRef = inject(DestroyRef);

  mode: VideoEditPanelMode = this.data.mode;
  video = signal<EditableVideo | undefined>(this.data.video);
  selectedTags?: string[] = this.data.selectedTags;

  editForm = this.formBuilder.group({
      name: [this.video()?.name ?? '', [Validators.required, this.validationService.nameValidator()]],
      author: [this.video()?.author ?? '', [this.validationService.authorValidator()]],
      loved: [this.video()?.loved ?? false],
      introduction: [this.video()?.introduction ?? '', [this.validationService.introductionValidator()]],
      tagInput: ['', [this.validationService.tagValidator()]],
      modifySeries: [false],
      seriesAction: ['set' as 'set' | 'clear'],
      seriesName: [this.video()?.seriesName ?? '', [this.validationService.seriesNameValidator()]],
  });

  tags = signal<string[]>([]);
  isSaving = signal<boolean>(false);

  seriesMembers = signal<BatchPanelVideoItem[]>([]);
  /* 
    Most recently confirmed series name: either the original name on check-in,
    or the last autocomplete suggestion the user picked. Typing into the input
    without picking a suggestion does not update this, so we can detect
    "user typed something new" and reset the list to just the current video.
  */
  private committedSeriesName = signal<string | null>(null);
  isLoadingSeriesMembers = signal<boolean>(false);

  modifySeries = toSignal(
    this.editForm.controls.modifySeries.valueChanges.pipe(startWith(this.editForm.controls.modifySeries.value)),
    { initialValue: false }
  );

  seriesAction = toSignal(
    this.editForm.controls.seriesAction.valueChanges.pipe(startWith(this.editForm.controls.seriesAction.value)),
    { initialValue: 'set' as 'set' | 'clear' }
  );

  currentVideoId = computed(() => this.video()?.id ?? null);

  authorSuggestions = this.mode === 'full'?
    toSignal(
      this.gqlService.getSuggestionsQuery(
        this.editForm.controls.author.valueChanges,
        SearchField.Author
      ),
      { initialValue: this.gqlService.initialSignalData<string[]>([]) }
    )
    : signal(this.gqlService.initialSignalData<string[]>([]));

  tagSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(
      this.editForm.controls.tagInput.valueChanges.pipe(
        startWith(this.editForm.controls.tagInput.value)
      ),
      SearchField.Tag
    ),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  )

  seriesSuggestions = this.mode === 'full' ?
    toSignal(
      this.editForm.controls.seriesName.valueChanges.pipe(
        startWith(this.editForm.controls.seriesName.value),
        debounceTime(300),
        distinctUntilChanged(),
        switchMap(value => this.gqlService.searchSeriesByPrefixQuery(value ?? '', 10))
      ),
      { initialValue: this.gqlService.initialSignalData<string[]>([]) }
    )
    : signal(this.gqlService.initialSignalData<string[]>([]));

  tagsError = computed(() => {
    const result = this.validationService.validateTagsArray(this.tags());
    return result.valid ? null : result.error;
  });

  isFullMode = computed(() => this.mode === 'full');

  saveButtonText = computed(() =>
    this.mode === 'filter' ? 'Apply Filter' : (this.isSaving() ? 'Saving...' : 'Save')
  );

  ngOnInit() { this.initializeFormState(); }

  private initializeFormState() {
    if (this.mode === 'full' && this.video) {
      this.editForm.patchValue({
        name: this.video()?.name,
        author: this.video()?.author,
        loved: this.video()?.loved,
        introduction: this.video()?.introduction,
        seriesName: this.video()?.seriesName ?? '',
      });
      this.tags.set(this.video()?.tags.map(tag => tag.name) ?? []);
    } else if (this.mode === 'filter' && this.selectedTags) {
      this.tags.set([...this.selectedTags]);
    }
  }

  onModifySeriesToggle(checked: boolean) {
    if (!checked) {
      // Revert any staged changes.
      this.seriesMembers.set([]);
      this.committedSeriesName.set(null);
      this.editForm.patchValue({
        seriesAction: 'set',
        seriesName: this.video()?.seriesName ?? '',
      });
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
      this.seriesMembers.set([this.currentVideoAsItem()]);
    }
  }

  selectSeriesSuggestion(name: string) {
    this.editForm.patchValue({ seriesName: name });
    this.committedSeriesName.set(name);
    this.loadSeriesMembers(name);
  }

  onSeriesNameInput(value: string) {
    const committed = this.committedSeriesName();
    if (committed === null) return;
    if (value !== committed) {
      // User is typing a brand-new name; seed list with just the current video.
      this.committedSeriesName.set(null);
      this.seriesMembers.set([this.currentVideoAsItem()]);
    }
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
          this.seriesMembers.set(mapped);
        },
        error: () => {
          this.isLoadingSeriesMembers.set(false);
          this.seriesMembers.set([this.currentVideoAsItem()]);
        },
      });
  }

  private buildSeriesInput(): SeriesFieldInput | undefined {
    const modify = this.editForm.value.modifySeries ?? false;
    if (!modify) return undefined;

    const action = this.editForm.value.seriesAction ?? 'set';
    if (action === 'clear') {
      return { clear: true };
    }

    const name = (this.editForm.value.seriesName ?? '').trim();
    if (!name) {
      return { clear: true };
    }

    const orders: SeriesOrderEntryInput[] = this.seriesMembers().map((item, index) => ({
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

  selectAuthorSuggestion(author: string) {
    this.editForm.patchValue({ author });
  }

  toggleLoved() {
    const currentLoved = this.editForm.get('loved')?.value;
    this.editForm.patchValue({ loved: !currentLoved });
  }

  addTag(tagValue?: string) {
    const value = tagValue || this.editForm.get('tagInput')?.value;

    if (!value || value.trim() === '') {
      return;
    }

    const trimmedTag = value.trim();

    const tagValidation = this.validationService.validateTag(trimmedTag);
    if (!tagValidation.valid) {
      return;
    }

    const tagsArrayValidation = this.validationService.validateTagsArray([...this.tags(), trimmedTag]);
    if (!tagsArrayValidation.valid) {
      return;
    }

    if (this.tags().includes(trimmedTag)) {
      this.editForm.patchValue({ tagInput: '' });
      return;
    }

    this.tags.update(tags => [...tags, trimmedTag]);

    this.editForm.patchValue({ tagInput: '' });
  }

  selectTagSuggestion(tag: string) {
    this.addTag(tag);
  }

  removeTag(tag: string) {
    this.tags.update(tags => tags.filter(t => t !== tag));
  }

  onTagInputEnter(event: Event) {
    event.preventDefault();
    this.addTag();
  }

  handleSave() {
    if (this.mode === 'filter') {
      this.dialogRef.close(this.tags());
    }
    else {
      if (this.editForm.valid && !this.tagsError() && this.video()) {
        const formValue = this.editForm.value;
        const seriesInput = this.buildSeriesInput();

        this.isSaving.set(true);

        this.gqlService.updateVideoMetadataMutation(
          this.video()!.id,
          formValue.loved ?? false,
          this.tags(),
          formValue.name ?? undefined,
          formValue.introduction ?? undefined,
          formValue.author ?? 'Unknown',
          seriesInput,
        )
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (result) => {
            this.isSaving.set(false);
            if (result.data?.success) {
              this.videoUpdateEventService.emitUpdated(this.affectedVideoIds(seriesInput));
              this.toastService.emitNewToast('Video information updated successfully.', ToastType.Success);
              this.dialogRef.close(result.data);
            } else {
              // update failed, keep the dialog open for user to retry
              this.toastService.emitNewToast('Failed to update video metadata.', ToastType.Error);
            }
          },
          error: (err) => {
            this.isSaving.set(false);
            this.toastService.emitNewToast('Error updating video metadata: ' + err.message, ToastType.Error);
          }
        });
      }
    }
  }

  handleCancel() {
    this.dialogRef.close();
  }
}
