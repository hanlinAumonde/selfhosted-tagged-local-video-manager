import { signal } from "@angular/core";
import { TestBed } from "@angular/core/testing";
import { form, SchemaPath, ValidationError } from "@angular/forms/signals";
import { of } from "rxjs";
import { toArray } from "rxjs/operators";

import { SearchField } from "../../core/graphql/generated/graphql";
import { SeriesEdit } from "../../shared/models/panels.model";
import { folderNameRule, maxLengthRule, seriesEditSchema, tagListRule } from "./validation.rules";
import { ValidationService } from "./validation.service";

/** Builds a string of `length` repeated characters. */
function chars(length: number): string {
    return "a".repeat(length);
}

/** Runs a schema rule against a single string field and returns the errors it reports. */
function stringRuleErrors(
    rule: (path: SchemaPath<string>) => void,
    value: string,
): readonly ValidationError[] {
    const model = signal(value);
    const field = TestBed.runInInjectionContext(() => form(model, path => rule(path)));
    return field().errors();
}

/** Runs a schema rule against a single string-array field and returns the errors it reports. */
function tagListRuleErrors(tags: string[]): readonly ValidationError[] {
    const model = signal(tags);
    const field = TestBed.runInInjectionContext(() => form(model, path => tagListRule(path)));
    return field().errors();
}

/** The error kinds a rule reported, in the order the rule produced them. */
function errorKinds(errors: readonly ValidationError[]): string[] {
    return errors.map(error => error.kind);
}

/** Builds a series edit form on the shared schema, ready to be inspected field by field. */
function seriesForm(initial: Partial<SeriesEdit> = {}) {
    const model = signal<SeriesEdit>({
        modify: false,
        action: "set",
        name: "",
        members: [],
        ...initial,
    });
    const field = TestBed.runInInjectionContext(() => form(model, seriesEditSchema));
    return { model, field };
}

/** Collects everything an operator lets through for a single emitted value. */
function emissionsThrough(
    operator: ReturnType<ValidationService["filterValidInput"]>,
    value: string | null,
): (string | null)[] {
    let received: (string | null)[] = [];
    of(value).pipe(operator, toArray()).subscribe(values => (received = values));
    return received;
}

describe("ValidationService", () => {
    let service: ValidationService;

    beforeEach(() => {
        TestBed.configureTestingModule({});
        service = TestBed.inject(ValidationService);
    });

    it("should be created", () => {
        expect(service).toBeTruthy();
    });

    // ==================== imperative validation methods ====================

    describe("validateTag", () => {
        it("accepts an empty tag", () => {
            // Given the tag rule
            // When an empty string is validated
            const result = service.validateTag("");
            // Then the result is valid, because emptiness is rejected elsewhere
            expect(result).toEqual({ valid: true });
        });

        it("accepts a whitespace-only tag", () => {
            // Given the tag rule
            // When a value of only spaces is validated
            const result = service.validateTag("   ");
            // Then the result is valid, because it trims to nothing and is treated as absent
            expect(result).toEqual({ valid: true });
        });

        it("accepts a tag exactly at 30 characters", () => {
            // Given the tag rule
            // When a 30-character tag is validated
            const result = service.validateTag(chars(30));
            // Then the result is valid
            expect(result).toEqual({ valid: true });
        });

        it("rejects a tag over 30 characters", () => {
            // Given the tag rule
            // When a 31-character tag is validated
            const result = service.validateTag(chars(31));
            // Then the result is invalid and its message names the 30-character limit
            expect(result).toEqual({ valid: false, error: "Tag maximum length is 30 characters" });
        });
    });

    describe("validateTagsArray", () => {
        it("accepts exactly 50 tags", () => {
            // Given the tag list rule
            // When a list of exactly 50 tags is validated
            const result = service.validateTagsArray(Array.from({ length: 50 }, (_, i) => `tag${i}`));
            // Then the result is valid, because the cap is inclusive
            expect(result).toEqual({ valid: true });
        });

        it("rejects 51 tags", () => {
            // Given the tag list rule
            // When a list of 51 tags is validated
            const result = service.validateTagsArray(Array.from({ length: 51 }, (_, i) => `tag${i}`));
            // Then the result is invalid and its message names the cap of 50
            expect(result).toEqual({ valid: false, error: "Maximum 50 tags allowed" });
        });

        it("accepts an empty list", () => {
            // Given the tag list rule
            // When an empty list is validated
            const result = service.validateTagsArray([]);
            // Then the result is valid
            expect(result).toEqual({ valid: true });
        });
    });

    // ==================== RxJS operator ====================

    describe("filterValidInput", () => {
        it("lets a null value through", () => {
            // Given the operator configured for the name field
            const operator = service.filterValidInput(SearchField.Name);
            // When a null value is emitted
            const received = emissionsThrough(operator, null);
            // Then it reaches the subscriber, because clearing the input is a meaningful event
            expect(received).toEqual([null]);
        });

        it("lets a name at 200 characters through", () => {
            // Given the operator configured for the name field
            const operator = service.filterValidInput(SearchField.Name);
            // When a 200-character value is emitted
            const received = emissionsThrough(operator, chars(200));
            // Then it reaches the subscriber
            expect(received).toEqual([chars(200)]);
        });

        it("blocks a name over 200 characters", () => {
            // Given the operator configured for the name field
            const operator = service.filterValidInput(SearchField.Name);
            // When a 201-character value is emitted
            const received = emissionsThrough(operator, chars(201));
            // Then nothing reaches the subscriber, so no suggestion query is issued for input that cannot be valid
            expect(received).toEqual([]);
        });

        it("blocks an author over 50 characters", () => {
            // Given the operator configured for the author field
            const operator = service.filterValidInput(SearchField.Author);
            // When a 51-character value is emitted
            const received = emissionsThrough(operator, chars(51));
            // Then nothing reaches the subscriber
            expect(received).toEqual([]);
        });

        it("blocks a tag over 30 characters", () => {
            // Given the operator configured for the tag field
            const operator = service.filterValidInput(SearchField.Tag);
            // When a 31-character value is emitted
            const received = emissionsThrough(operator, chars(31));
            // Then nothing reaches the subscriber
            expect(received).toEqual([]);
        });

        it("blocks a value for an unrecognised field", () => {
            // Given the operator configured with a field outside the SearchField enum
            const operator = service.filterValidInput("Unknown" as SearchField);
            // When any non-empty value is emitted
            const received = emissionsThrough(operator, "anything");
            // Then nothing reaches the subscriber, because the defensive default rejects unknown fields
            expect(received).toEqual([]);
        });
    });
});

describe("Signal Forms validation rules", () => {
    /**
     * These rules replaced the ValidatorFn factories ValidationService used to expose.
     * The boundaries below were pinned against those validators before they were deleted.
     */
    let service: ValidationService;

    beforeEach(() => {
        TestBed.configureTestingModule({});
        service = TestBed.inject(ValidationService);
    });

    describe("maxLengthRule", () => {
        it("accepts a value exactly at the limit", () => {
            // Given the rule bound to a field with a limit of 10
            // When the field holds exactly 10 characters
            const errors = stringRuleErrors(path => maxLengthRule(path, 10), chars(10));
            // Then it reports no error, because the limit is inclusive
            expect(errors).toEqual([]);
        });

        it("rejects a value one character over the limit", () => {
            // Given the rule bound to a field with a limit of 10
            // When the field holds 11 characters
            const errors = stringRuleErrors(path => maxLengthRule(path, 10), chars(11));
            // Then it reports a single `maxLength` error
            expect(errorKinds(errors)).toEqual(["maxLength"]);
        });

        it("carries a message naming the limit", () => {
            // Given the rule bound to a field with a limit of 10
            // When the field holds 11 characters
            const errors = stringRuleErrors(path => maxLengthRule(path, 10), chars(11));
            // Then the message names the limit, so the template no longer has to build the text
            expect(errors[0].message).toBe("Maximum length is 10 characters");
        });

        it("measures length after trimming surrounding whitespace", () => {
            // Given the rule bound to a field with a limit of 10
            // When the field holds 10 characters padded with spaces
            const errors = stringRuleErrors(path => maxLengthRule(path, 10), `   ${chars(10)}   `);
            // Then it reports no error: unlike the built-in maxLength, this rule trims first
            expect(errors).toEqual([]);
        });

        it("accepts an empty value", () => {
            // Given the rule bound to a field with a limit of 10
            // When the field is empty
            const errors = stringRuleErrors(path => maxLengthRule(path, 10), "");
            // Then it reports no error, leaving emptiness to a `required` rule
            expect(errors).toEqual([]);
        });
    });

    describe("folderNameRule", () => {
        it("rejects an empty name as required", () => {
            // Given the folder name rule
            // When the field is empty
            const errors = stringRuleErrors(folderNameRule, "");
            // Then it reports `required`
            expect(errorKinds(errors)).toEqual(["required"]);
        });

        it("rejects a whitespace-only name as required", () => {
            // Given the folder name rule
            // When the field holds only spaces
            const errors = stringRuleErrors(folderNameRule, "    ");
            // Then it reports `required`, because the value is trimmed before being judged
            expect(errorKinds(errors)).toEqual(["required"]);
        });

        it("rejects a name containing a forward slash", () => {
            // Given the folder name rule
            // When the field holds "season/1"
            const errors = stringRuleErrors(folderNameRule, "season/1");
            // Then it reports `folderSeparator`
            expect(errorKinds(errors)).toEqual(["folderSeparator"]);
        });

        it("rejects a name containing a backslash", () => {
            // Given the folder name rule
            // When the field holds "season\\1"
            const errors = stringRuleErrors(folderNameRule, "season\\1");
            // Then it reports `folderSeparator`
            expect(errorKinds(errors)).toEqual(["folderSeparator"]);
        });

        it("rejects a single dot", () => {
            // Given the folder name rule
            // When the field holds "."
            const errors = stringRuleErrors(folderNameRule, ".");
            // Then it reports `folderRelativeReference`
            expect(errorKinds(errors)).toEqual(["folderRelativeReference"]);
        });

        it("rejects a double dot", () => {
            // Given the folder name rule
            // When the field holds ".."
            const errors = stringRuleErrors(folderNameRule, "..");
            // Then it reports `folderRelativeReference`
            expect(errorKinds(errors)).toEqual(["folderRelativeReference"]);
        });

        it("accepts a name that merely starts with a dot", () => {
            // Given the folder name rule
            // When the field holds ".hidden"
            const errors = stringRuleErrors(folderNameRule, ".hidden");
            // Then it reports no error
            expect(errors).toEqual([]);
        });

        it("rejects a name over 200 characters", () => {
            // Given the folder name rule
            // When the field holds 201 characters
            const errors = stringRuleErrors(folderNameRule, chars(201));
            // Then it reports `maxLength`
            expect(errorKinds(errors)).toEqual(["maxLength"]);
        });

        it("reports the separator error in preference to the length error", () => {
            // Given the folder name rule
            // When the field holds a 201-character name that also contains "/"
            const errors = stringRuleErrors(folderNameRule, `${chars(200)}/`);
            // Then it reports only `folderSeparator`: the checks stop at the first failure
            expect(errorKinds(errors)).toEqual(["folderSeparator"]);
        });

        it("accepts an ordinary folder name", () => {
            // Given the folder name rule
            // When the field holds "Season 1"
            const errors = stringRuleErrors(folderNameRule, "Season 1");
            // Then it reports no error
            expect(errors).toEqual([]);
        });

        /*
          The messages moved out of NewFolderPanel's errorMessage() and into the rule. They are
          asserted verbatim so centralising them cannot quietly reword what the user reads.
        */
        it("keeps the wording the panel used for a missing name", () => {
            // Given the folder name rule
            // When the field is empty
            const errors = stringRuleErrors(folderNameRule, "");
            // Then the message is the one the panel used to build
            expect(errors[0].message).toBe("A folder name is required");
        });

        it("keeps the wording the panel used for a separator", () => {
            // Given the folder name rule
            // When the field holds "season/1"
            const errors = stringRuleErrors(folderNameRule, "season/1");
            // Then the message is the one the panel used to build
            expect(errors[0].message).toBe('A folder name cannot contain "/" or "\\"');
        });

        it("keeps the wording the panel used for a relative reference", () => {
            // Given the folder name rule
            // When the field holds ".."
            const errors = stringRuleErrors(folderNameRule, "..");
            // Then the message is the one the panel used to build
            expect(errors[0].message).toBe("That is not a folder name");
        });

        it("keeps the wording the panel used for an over-long name", () => {
            // Given the folder name rule
            // When the field holds 201 characters
            const errors = stringRuleErrors(folderNameRule, chars(201));
            // Then the message is the one the panel used to build
            expect(errors[0].message).toBe("Maximum length is 200 characters");
        });
    });

    describe("tagListRule", () => {
        it("accepts exactly 50 tags", () => {
            // Given the tag list rule
            // When the field holds exactly 50 tags
            const errors = tagListRuleErrors(Array.from({ length: 50 }, (_, i) => `tag${i}`));
            // Then it reports no error, because the cap is inclusive
            expect(errors).toEqual([]);
        });

        it("rejects 51 tags", () => {
            // Given the tag list rule
            // When the field holds 51 tags
            const errors = tagListRuleErrors(Array.from({ length: 51 }, (_, i) => `tag${i}`));
            // Then it reports a `maxTags` error, the rule that used to live outside the form entirely
            expect(errorKinds(errors)).toEqual(["maxTags"]);
        });

        it("carries a message naming the cap", () => {
            // Given the tag list rule
            // When the field holds 51 tags
            const errors = tagListRuleErrors(Array.from({ length: 51 }, (_, i) => `tag${i}`));
            // Then the message matches the one validateTagsArray produced
            expect(errors[0].message).toBe("Maximum 50 tags allowed");
        });

        it("accepts an empty list", () => {
            // Given the tag list rule
            // When the field holds no tags
            const errors = tagListRuleErrors([]);
            // Then it reports no error
            expect(errors).toEqual([]);
        });
    });

    describe("seriesEditSchema", () => {
        it("caps the series name at 100 characters", () => {
            // Given a series edit the user has opted into
            const { field } = seriesForm({ modify: true, name: chars(101) });
            // When the name is one character over the limit
            // Then it reports maxLength
            expect(errorKinds(field.name().errors())).toEqual(["maxLength"]);
        });

        it("accepts a series name at exactly 100 characters", () => {
            // Given a series edit the user has opted into
            const { field } = seriesForm({ modify: true, name: chars(100) });
            // When the name is exactly at the limit
            // Then it reports no error
            expect(field.name().errors()).toEqual([]);
        });

        /*
          `modify` off means the panel leaves the series fields alone entirely, so a stale
          over-long name must not be able to block the rest of the form from saving.
        */
        it("ignores the name while the user has not opted in", () => {
            // Given an over-long name but `modify` left off
            const { field } = seriesForm({ modify: false, name: chars(101) });
            // When the form is judged
            // Then the name is disabled and contributes nothing
            expect(field.name().disabled()).toBe(true);
            expect(field().valid()).toBe(true);
        });

        it("ignores the name when the action is to clear the series", () => {
            // Given an over-long name while clearing
            const { field } = seriesForm({ modify: true, action: "clear", name: chars(101) });
            // When the form is judged
            // Then the name is disabled, because clearing does not use it
            expect(field.name().disabled()).toBe(true);
            expect(field().valid()).toBe(true);
        });

        it("validates the name once the user opts in and assigns", () => {
            // Given an over-long name with modify on and the action set to assign
            const { field } = seriesForm({ modify: true, action: "set", name: chars(101) });
            // When the form is judged
            // Then the name is live and the form is invalid
            expect(field.name().disabled()).toBe(false);
            expect(field().valid()).toBe(false);
        });

        it("hides the member ordering unless assigning a name", () => {
            // Given a series edit that is clearing rather than assigning
            const { field } = seriesForm({ modify: true, action: "clear" });
            // When the members field is inspected
            // Then it is hidden, so no ordering is collected for an operation that discards it
            expect(field.members().hidden()).toBe(true);
        });

        it("shows the member ordering while assigning", () => {
            // Given a series edit that is assigning a name
            const { field } = seriesForm({ modify: true, action: "set" });
            // When the members field is inspected
            // Then it is visible
            expect(field.members().hidden()).toBe(false);
        });
    });

});
