import { Component, computed, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { apply, form, FormField, FormRoot, submit } from '@angular/forms/signals';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
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
import { environment } from '../../../../environments/environment';
import { SearchField } from '../../../core/graphql/generated/graphql';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { maxLengthRule, tagListRule } from '../../../services/validation-service/validation.rules';
import { DirectorySearchCriteria, SearchPanelData } from '../../models/panels.model';
import { TagChipInput } from '../tag-chip-input/tag-chip-input';

@Component({
  selector: 'app-search-panel',
  imports: [
    FormField,
    FormRoot,
    MatAutocompleteModule,
    MatButtonModule,
    MatDialogActions,
    MatDialogClose,
    MatDialogContent,
    MatDialogTitle,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    TagChipInput
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './search-panel.html'
})
export class SearchPanel {
  readonly dialogRef = inject(MatDialogRef<SearchPanel, DirectorySearchCriteria>);
  readonly data = inject<SearchPanelData>(MAT_DIALOG_DATA);
  private gqlService = inject(GqlService);

  protected searchModel = signal({
    name: '',
    author: '',
    tags: [] as string[]
  });

  searchForm = form(
    this.searchModel,
    path => {
      maxLengthRule(path.name, environment.VALIDATION_RULES.NAME_MAX_LENGTH);
      maxLengthRule(path.author, environment.VALIDATION_RULES.AUTHOR_MAX_LENGTH);
      apply(path.tags, tagListRule);
    },
    { submission: { action: () => this.closeWithCriteria() } },
  );

  nameSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(
      toObservable(computed(() => this.searchModel().name)),
      SearchField.Name
    ),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  authorSuggestions = toSignal(
    this.gqlService.getSuggestionsQuery(
      toObservable(computed(() => this.searchModel().author)),
      SearchField.Author
    ),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) }
  );

  /**
   * A search with every field blank is the listing the browser already shows, and the
   * backend refuses it rather than walking the whole tree for nothing.
   */
  canSearch = computed(() => {
    const draft = this.searchModel();
    return !!(draft.name.trim() || draft.author.trim() || draft.tags.length > 0);
  });

  search() {
    if (!this.canSearch()) return;
    submit(this.searchForm);
  }

  private async closeWithCriteria(): Promise<null> {
    const draft = this.searchModel();
    this.dialogRef.close({
      name: draft.name.trim(),
      author: draft.author.trim(),
      tags: draft.tags
    });
    return null;
  }
}
