import { ChangeDetectionStrategy, Component, inject, input, model, output } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { FormValueControl, ValidationError } from '@angular/forms/signals';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';
import { GqlService } from '../../../services/GQL-service/GQL.service';

const SUGGESTION_LIMIT = 10;

/**
 * Series name field with prefix-matched suggestions, shared by the single-video and batch
 * panels. Picking a suggestion is reported separately from typing, because a caller that
 * tracks series membership has to tell "joined an existing series" from "named a new one".
 */
@Component({
  selector: 'app-series-name-input',
  imports: [
    MatAutocompleteModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './series-name-input.html',
})
export class SeriesNameInput implements FormValueControl<string> {
  private gqlService = inject(GqlService);

  value = model('');
  errors = input<readonly ValidationError.WithOptionalFieldTree[]>([]);
  disabled = input(false);
  touch = output<void>();

  suggestionPicked = output<string>();

  protected suggestions = toSignal(
    toObservable(this.value).pipe(
      debounceTime(300),
      distinctUntilChanged(),
      switchMap(prefix => this.gqlService.searchSeriesByPrefixQuery(prefix ?? '', SUGGESTION_LIMIT)),
    ),
    { initialValue: this.gqlService.initialSignalData<string[]>([]) },
  );

  protected onInput(event: Event) {
    this.value.set((event.target as HTMLInputElement).value);
  }

  protected pick(name: string) {
    this.value.set(name);
    this.suggestionPicked.emit(name);
  }
}
