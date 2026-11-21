import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatAutocompleteHarness } from '@angular/material/autocomplete/testing';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';

import { TagChipInput } from './tag-chip-input';
import { GetSuggestionsDocument } from '../../../core/graphql/generated/graphql';
import { apolloAsInTheApp } from '../../../../testing/apollo-testing';

const tick = (ms = 0) => new Promise<void>(resolve => setTimeout(resolve, ms));
/** Tag suggestions are asked for this long after typing pauses. */
const SUGGESTION_DEBOUNCE = 500;

describe('TagChipInput', () => {
  let fixture: ComponentFixture<TagChipInput>;
  let apollo: ApolloTestingController;
  let rejected: string[];

  async function showTags(tags: string[], disallowed: string[] = []) {
    TestBed.configureTestingModule({ imports: [ApolloTestingModule] });
    apollo = apolloAsInTheApp();
    fixture = TestBed.createComponent(TagChipInput);
    fixture.componentRef.setInput('value', tags);
    fixture.componentRef.setInput('disallowed', disallowed);
    rejected = [];
    fixture.componentInstance.rejected.subscribe(tag => rejected.push(tag));
    await settle();
  }

  async function settle() {
    await tick();
    await fixture.whenStable();
  }

  const element = () => fixture.nativeElement as HTMLElement;
  const input = () => element().querySelector('input')!;
  const tags = () => fixture.componentInstance.value();

  async function type(text: string) {
    input().value = text;
    input().dispatchEvent(new Event('input'));
    await settle();
  }

  async function enter(text: string) {
    await type(text);
    input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
  }

  it('adds the typed tag on Enter, trimmed, and clears the input', async () => {
    /*
      Given the list holds "a"
      When the user types "  b  " and presses Enter
      Then the list holds "a" and "b", and the input is empty
    */
    await showTags(['a']);

    await enter('  b  ');

    expect(tags()).toEqual(['a', 'b']);
    expect(input().value).toBe('');
  });

  it('adds a tag picked from the suggestions', async () => {
    /*
      Given the user types "ca" and the suggestions are "cat" and "car"
      When the user picks "car"
      Then the list holds "car"
    */
    await showTags([]);
    const autocomplete = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatAutocompleteHarness);

    await autocomplete.enterText('ca');
    await tick(SUGGESTION_DEBOUNCE + 50);
    apollo.expectOne(GetSuggestionsDocument).flushData({ getSuggestions: ['cat', 'car'] });
    await settle();
    await autocomplete.selectOption({ text: 'car' });
    await settle();

    expect(tags()).toEqual(['car']);
  });

  it('does not add a blank, a duplicate, a too long or one tag too many', async () => {
    /*
      Given the list holds "a"
      When the user enters "   ", "a" and a 31-character tag
      Then the list still holds only "a"
      Given instead the list holds 50 tags
      When the user enters "one-more"
      Then it is not added
    */
    await showTags(['a']);
    for (const typed of ['   ', 'a', 'x'.repeat(31)]) await enter(typed);
    expect(tags()).toEqual(['a']);

    const fifty = Array.from({ length: 50 }, (_, i) => `t${i}`);
    fixture.componentRef.setInput('value', fifty);
    await enter('one-more');
    expect(tags()).toEqual(fifty);
  });

  it('refuses a tag the parent does not accept, and says which', async () => {
    /*
      Given the parent does not accept "todo"
      When the user enters "todo"
      Then "todo" is not added and is reported as rejected
    */
    await showTags([], ['todo']);

    await enter('todo');

    expect(tags()).toEqual([]);
    expect(rejected).toEqual(['todo']);
  });

  it('removes a tag', async () => {
    /*
      Given the list holds "a" and "b"
      When the user removes "a"
      Then the list holds "b"
    */
    await showTags(['a', 'b']);

    element().querySelector<HTMLButtonElement>('button[aria-label="Remove a"]')!.click();
    await settle();

    expect(tags()).toEqual(['b']);
  });

  it('shows the error the parent form reports', async () => {
    /*
      Given the parent form reports "Too many tags"
      Then the input shows "Too many tags"
    */
    await showTags(['a']);

    fixture.componentRef.setInput('errors', [{ kind: 'tags', message: 'Too many tags' }]);
    await settle();

    expect(element().textContent).toContain('Too many tags');
  });
});
