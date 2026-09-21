import { ChangeDetectionStrategy, Component, computed, inject, input, model, output, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { FormValueControl, ValidationError } from '@angular/forms/signals';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { SearchField } from '../../../core/graphql/generated/graphql';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { ValidationService } from '../../../services/validation-service/validation.service';

/**
 * Edits a list of tags as removable chips with an autocompleting input.
 *
 * The text being typed is deliberately not part of the value: a parent form stores the
 * committed list and nothing else, which is what lets the tag rules live in its schema.
 */
@Component({
  selector: 'app-tag-chip-input',
  imports: [
    MatAutocompleteModule,
    MatChipsModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './tag-chip-input.html',
})
export class TagChipInput implements FormValueControl<string[]> {
  private gqlService = inject(GqlService);
  private validationService = inject(ValidationService);

  /** The committed tag list — the only part the parent form stores. */
  value = model<string[]>([]);

  /** Errors reported by the bound field, such as the list-size cap. */
  errors = input<readonly ValidationError.WithOptionalFieldTree[]>([]);

  /** Raised on blur so the bound field can become touched. */
  touch = output<void>();

  /** Empty means the caller labels the block itself and no inner label is rendered. */
  label = input('Tags');
  placeholder = input('');
  /** Extra classes for each chip, used to colour-code add versus remove lists. */
  chipClass = input('');
  emptyHint = input('No tag-suggestions available, press Enter to add as new tag');

  /**
   * Tags the parent will not accept, with the reason. Adding one is refused and reported
   * through `rejected` rather than silently dropped.
   */
  disallowed = input<readonly string[]>([]);
  rejected = output<string>();

  /** The text being typed. Never leaves this component. */
  protected draft = signal('');

  protected suggestions = toSignal(
    this.gqlService.getSuggestionsQuery(toObservable(this.draft), SearchField.Tag),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) },
  );

  /** Length complaint about the text being typed, which the bound field cannot see. */
  protected draftError = computed(() => {
    const result = this.validationService.validateTag(this.draft());
    return result.valid ? null : result.error;
  });

  protected onDraftInput(event: Event) {
    this.draft.set((event.target as HTMLInputElement).value);
  }

  protected onEnter(event: Event) {
    event.preventDefault();
    this.commit();
  }

  /** Moves the typed text (or a picked suggestion) into the list. */
  protected commit(tag?: string) {
    const candidate = (tag ?? this.draft()).trim();
    if (!candidate) return;
    if (!this.validationService.validateTag(candidate).valid) return;

    if (this.disallowed().includes(candidate)) {
      this.rejected.emit(candidate);
      return;
    }
    if (!this.validationService.validateTagsArray([...this.value(), candidate]).valid) return;

    if (!this.value().includes(candidate)) {
      this.value.update(tags => [...tags, candidate]);
    }
    this.draft.set('');
  }

  protected remove(tag: string) {
    this.value.update(tags => tags.filter(t => t !== tag));
  }
}
