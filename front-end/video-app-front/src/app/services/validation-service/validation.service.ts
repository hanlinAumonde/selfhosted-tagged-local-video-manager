import { Injectable } from '@angular/core';
import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';
import { MonoTypeOperatorFunction, pipe } from 'rxjs';
import { filter } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import { SearchField } from '../../core/graphql/generated/graphql';

const REGEX_SPECIAL_CHARS = /[.*+?^${}()|[\]\\]/g;

/** Characters that would make a folder name address something other than one child. */
const FOLDER_NAME_SEPARATORS = ['/', '\\'];

export interface ValidationResult {
  valid: boolean;
  error?: string;
}

@Injectable({
  providedIn: 'root'
})
export class ValidationService {

  // ==================== synchronous validation methods ====================

  validateStringLength(value: string | null | undefined, maxLength: number): ValidationResult {
    if (!value) return { valid: true };
    const trimmed = value.trim();
    if (trimmed.length > maxLength) {
      return { valid: false, error: `Maximum length is ${maxLength} characters` };
    }
    return { valid: true };
  }

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

  validatePageNumber(value: number | null | undefined): ValidationResult {
    if (value === null || value === undefined) return { valid: true };
    if (value < environment.VALIDATION_RULES.PAGE_NUMBER_MIN || value > environment.VALIDATION_RULES.PAGE_NUMBER_MAX) {
      return {
        valid: false,
        error: `Page number must be between ${environment.VALIDATION_RULES.PAGE_NUMBER_MIN} and ${environment.VALIDATION_RULES.PAGE_NUMBER_MAX}`
      };
    }
    return { valid: true };
  }

  validateSearchKeyword(value: string | null | undefined): ValidationResult {
    return this.validateStringLength(value, environment.VALIDATION_RULES.NAME_MAX_LENGTH);
  }

  sanitizeAndValidate(value: string | null | undefined, maxLength: number): string | null {
    if (!value) return null;
    const trimmed = value.trim();
    if (trimmed.length === 0) return null;
    return trimmed.substring(0, maxLength);
  }

  // ==================== Angular Reactive Forms Validators ====================

  maxLengthValidator(maxLength: number): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
      const value = control.value;
      if (!value) return null;
      const trimmed = typeof value === 'string' ? value.trim() : String(value);
      if (trimmed.length > maxLength) {
        return { maxLength: { max: maxLength, actual: trimmed.length } };
      }
      return null;
    };
  }

  tagValidator(): ValidatorFn {
    return this.maxLengthValidator(environment.VALIDATION_RULES.TAG_MAX_LENGTH);
  }

  nameValidator(): ValidatorFn {
    return this.maxLengthValidator(environment.VALIDATION_RULES.NAME_MAX_LENGTH);
  }

  authorValidator(): ValidatorFn {
    return this.maxLengthValidator(environment.VALIDATION_RULES.AUTHOR_MAX_LENGTH);
  }

  introductionValidator(): ValidatorFn {
    return this.maxLengthValidator(environment.VALIDATION_RULES.INTRODUCTION_MAX_LENGTH);
  }

  seriesNameValidator(): ValidatorFn {
    return this.maxLengthValidator(environment.VALIDATION_RULES.SERIES_NAME_MAX_LENGTH);
  }

  searchKeywordValidator(): ValidatorFn {
    return this.maxLengthValidator(environment.VALIDATION_RULES.NAME_MAX_LENGTH);
  }

  /**
   * Mirrors the rules the backend enforces on a new folder name, so the dialog can say
   * what is wrong before a round-trip. The backend still rejects the same names — this
   * one is for the message, that one is for the guarantee.
   */
  folderNameValidator(): ValidatorFn {
    return (control: AbstractControl): ValidationErrors | null => {
      const trimmed = typeof control.value === 'string' ? control.value.trim() : '';
      if (!trimmed) {
        return { required: true };
      }
      if (FOLDER_NAME_SEPARATORS.some(separator => trimmed.includes(separator))) {
        return { folderSeparator: true };
      }
      if (trimmed === '.' || trimmed === '..') {
        return { folderRelativeReference: true };
      }
      const maxLength = environment.VALIDATION_RULES.NAME_MAX_LENGTH;
      if (trimmed.length > maxLength) {
        return { maxLength: { max: maxLength, actual: trimmed.length } };
      }
      return null;
    };
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
