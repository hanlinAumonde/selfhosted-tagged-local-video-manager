import { ChangeDetectionStrategy, Component, computed, inject, input, model, output, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { form, FormValueControl, ValidationError, FormField } from '@angular/forms/signals';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { SearchField } from '../../../core/graphql/generated/graphql';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { ValidationService } from '../../../services/validation-service/validation.service';
import { maxLengthRule } from '../../../services/validation-service/validation.rules';
import { environment } from '../../../../environments/environment';

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
    FormField
],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './tag-chip-input.html',
})
export class TagChipInput implements FormValueControl<string[]> {
  private gqlService = inject(GqlService);
  private validationService = inject(ValidationService);

  value = model<string[]>([]);

  errors = input<readonly ValidationError.WithOptionalFieldTree[]>([]);

  touch = output<void>();

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

  formModel = signal({ content: '' });
  tagInput = computed(() => this.formModel().content);

  form = form(this.formModel, path => {
    maxLengthRule(path.content, environment.VALIDATION_RULES.TAG_MAX_LENGTH)
  })

  protected suggestions = toSignal(
    this.gqlService.getSuggestionsQuery(toObservable(this.tagInput), SearchField.Tag),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) },
  );
  
  protected readonly displayNothing = () => '';

  protected onEnter(event: Event) {
    event.preventDefault();
    this.commit();
  }

  /** Moves the typed text (or a picked suggestion) into the list. */
  protected commit(tag?: string) {
    const candidate = (tag ?? this.tagInput()).trim();
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
    this.formModel.set({ content:'' })
  }

  protected remove(tag: string) {
    this.value.update(tags => tags.filter(t => t !== tag));
  }  
}
