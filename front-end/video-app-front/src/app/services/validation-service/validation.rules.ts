import { disabled, hidden, maxLengthError, requiredError, schema, SchemaPath, validate } from '@angular/forms/signals';

import { environment } from '../../../environments/environment';
import { SeriesEdit } from '../../shared/models/panels.model';

/** Characters that would make a folder name address something other than one child. */
const FOLDER_NAME_SEPARATORS = ['/', '\\'];

/**
 * Validation rules bound to form fields.
 *
 * These are plain functions rather than methods on ValidationService because schemas are
 * often declared at module scope, outside any injection context.
 */

/**
 * Caps a text field's length, reporting the limit in the message so templates need not build it.
 *
 * The built-in `maxLength` measures the raw value; this one measures the trimmed value.
 * Surrounding whitespace is therefore free, and a value that is only over the limit because
 * of padding stays valid.
 */
export function maxLengthRule(path: SchemaPath<string>, max: number): void {
  validate(path, ({ value }) => {
    const trimmed = value().trim();
    return trimmed.length > max
      ? maxLengthError(max, { message: `Maximum length is ${max} characters` })
      : null;
  });
}

/**
 * Mirrors the rules the backend enforces on a new folder name, so the dialog can say
 * what is wrong before a round-trip. The backend still rejects the same names — this
 * one is for the message, that one is for the guarantee.
 */
export function folderNameRule(path: SchemaPath<string>): void {
  validate(path, ({ value }) => {
    const trimmed = value().trim();
    if (!trimmed) {
      return requiredError({ message: 'A folder name is required' });
    }
    if (FOLDER_NAME_SEPARATORS.some(separator => trimmed.includes(separator))) {
      return { kind: 'folderSeparator', message: 'A folder name cannot contain "/" or "\\"' };
    }
    if (trimmed === '.' || trimmed === '..') {
      return { kind: 'folderRelativeReference', message: 'That is not a folder name' };
    }
    const max = environment.VALIDATION_RULES.NAME_MAX_LENGTH;
    if (trimmed.length > max) {
      return maxLengthError(max, { message: `Maximum length is ${max} characters` });
    }
    return null;
  });
}

/** Caps how many tags a field may hold. This rule used to live outside the form, in a computed. */
export function tagListRule(path: SchemaPath<string[]>): void {
  validate(path, ({ value }) => {
    const max = environment.VALIDATION_RULES.MAX_TAGS_COUNT;
    if (value().length > max) {
      return { kind: 'maxTags', message: `Maximum ${max} tags allowed` };
    }
    return null;
  });
}

/**
 * Rules for the series half of an edit form, shared by the single-video and batch panels.
 *
 * `disabled` and `hidden` do the work that conditional rendering used to: a field that is
 * off does not validate and does not reach the parent's validity, so a stale name left over
 * from a cancelled edit cannot block a save that no longer touches the series.
 */
export const seriesEditSchema = schema<SeriesEdit>(path => {
  maxLengthRule(path.name, environment.VALIDATION_RULES.SERIES_NAME_MAX_LENGTH);

  disabled(path.name, {
    when: ({ valueOf }) => !valueOf(path.modify) || valueOf(path.action) === 'clear',
  });

  // Clearing a series discards any ordering, so none is collected for it.
  hidden(path.members, {
    when: ({ valueOf }) => !valueOf(path.modify) || valueOf(path.action) === 'clear',
  });
});
