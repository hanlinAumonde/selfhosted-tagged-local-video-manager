import { Component, computed, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import {
  MAT_DIALOG_DATA,
  MatDialogActions,
  MatDialogClose,
  MatDialogContent,
  MatDialogRef,
  MatDialogTitle
} from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { startWith } from 'rxjs/operators';
import { SearchField } from '../../../core/graphql/generated/graphql';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { ValidationService } from '../../../services/validation-service/validation.service';
import { DirectorySearchCriteria, SearchPanelData } from '../../models/panels.model';

@Component({
  selector: 'app-search-panel',
  imports: [
    ReactiveFormsModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatChipsModule,
    MatDialogActions,
    MatDialogClose,
    MatDialogContent,
    MatDialogTitle,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './search-panel.html'
})
export class SearchPanel {
  readonly dialogRef = inject(MatDialogRef<SearchPanel, DirectorySearchCriteria>);
  readonly data = inject<SearchPanelData>(MAT_DIALOG_DATA);
  private fb = inject(FormBuilder);
  private gqlService = inject(GqlService);
  private validationService = inject(ValidationService);

  searchForm = this.fb.group({
    name: ['', [this.validationService.searchKeywordValidator()]],
    author: ['', [this.validationService.authorValidator()]],
    tagInput: ['', [this.validationService.tagValidator()]]
  });

  tags = signal<string[]>([]);

  nameSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(this.searchForm.controls.name.valueChanges, SearchField.Name),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  authorSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(this.searchForm.controls.author.valueChanges, SearchField.Author),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  tagSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(
      this.searchForm.controls.tagInput.valueChanges.pipe(
        startWith(this.searchForm.controls.tagInput.value)
      ),
      SearchField.Tag
    ),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  private formValue = toSignal(
    this.searchForm.valueChanges.pipe(startWith(this.searchForm.value)),
    { initialValue: this.searchForm.value }
  );

  /**
   * A search with every field blank is the listing the browser already shows, and the
   * backend refuses it rather than walking the whole tree for nothing.
   */
  canSearch = computed(() => {
    const value = this.formValue();
    return !!(value.name?.trim() || value.author?.trim() || this.tags().length > 0);
  });

  addTag(tagValue?: string) {
    const value = (tagValue || this.searchForm.value.tagInput || '').trim();
    if (!value) return;
    if (!this.validationService.validateTag(value).valid) return;
    if (!this.validationService.validateTagsArray([...this.tags(), value]).valid) return;

    if (!this.tags().includes(value)) {
      this.tags.update(tags => [...tags, value]);
    }
    this.searchForm.patchValue({ tagInput: '' });
  }

  removeTag(tag: string) {
    this.tags.update(tags => tags.filter(t => t !== tag));
  }

  onTagInputEnter(event: Event) {
    event.preventDefault();
    this.addTag();
  }

  search() {
    if (this.searchForm.invalid || !this.canSearch()) return;
    this.dialogRef.close({
      name: (this.searchForm.value.name ?? '').trim(),
      author: (this.searchForm.value.author ?? '').trim(),
      tags: this.tags()
    });
  }
}
