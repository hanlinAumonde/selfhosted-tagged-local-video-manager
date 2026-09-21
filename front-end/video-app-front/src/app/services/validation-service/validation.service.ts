import { Injectable } from '@angular/core';
import { MonoTypeOperatorFunction, pipe } from 'rxjs';
import { filter } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import { SearchField } from '../../core/graphql/generated/graphql';

export interface ValidationResult {
  valid: boolean;
  error?: string;
}

/**
 * Imperative validation helpers. Rules that bind to a form live in `validation.rules.ts`
 * instead, as Signal Forms schema rules.
 */
@Injectable({
  providedIn: 'root'
})
export class ValidationService {

  // ==================== synchronous validation methods ====================

  validateTag(value: string | null | undefined): ValidationResult {
    if (!value) return { valid: true };
    const trimmed = value.trim();
    if (trimmed.length === 0) return { valid: true };
    if (trimmed.length > environment.VALIDATION_RULES.TAG_MAX_LENGTH) {
      return { valid: false, error: `Tag maximum length is ${environment.VALIDATION_RULES.TAG_MAX_LENGTH} characters` };
    }
    return { valid: true };
  }

  validateTagsArray(tags: string[]): ValidationResult {
    if (tags.length > environment.VALIDATION_RULES.MAX_TAGS_COUNT) {
      return { valid: false, error: `Maximum ${environment.VALIDATION_RULES.MAX_TAGS_COUNT} tags allowed` };
    }
    return { valid: true };
  }

  // ==================== RxJS Operator ====================

  filterValidInput(field: SearchField): MonoTypeOperatorFunction<string | null> {
    return pipe(
      filter((value: string | null) => {
        if (!value) return true;
        let maxLength = 0;
        switch (field) {
          case SearchField.Name:
            maxLength = environment.VALIDATION_RULES.NAME_MAX_LENGTH;
            break;
          case SearchField.Author:
            maxLength = environment.VALIDATION_RULES.AUTHOR_MAX_LENGTH;
            break;
          case SearchField.Tag:
            maxLength = environment.VALIDATION_RULES.TAG_MAX_LENGTH;
            break;
          default:
            return false;
        }
        return value.trim().length <= maxLength;
      })
    );
  }
}
