import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatAutocompleteHarness } from '@angular/material/autocomplete/testing';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';

import { SeriesNameInput } from './series-name-input';
import { SearchSeriesByPrefixDocument } from '../../../core/graphql/generated/graphql';
import { apolloAsInTheApp } from '../../../../testing/apollo-testing';

const tick = (ms = 0) => new Promise<void>(resolve => setTimeout(resolve, ms));
/** Series suggestions are asked for this long after typing pauses. */
const SUGGESTION_DEBOUNCE = 300;

describe('SeriesNameInput', () => {
  let fixture: ComponentFixture<SeriesNameInput>;
  let apollo: ApolloTestingController;
  let picked: string[];
  let autocomplete: MatAutocompleteHarness;

  beforeEach(async () => {
    TestBed.configureTestingModule({ imports: [ApolloTestingModule] });
    apollo = apolloAsInTheApp();
    fixture = TestBed.createComponent(SeriesNameInput);
    picked = [];
    fixture.componentInstance.suggestionPicked.subscribe(name => picked.push(name));
    autocomplete = await TestbedHarnessEnvironment.loader(fixture).getHarness(MatAutocompleteHarness);
    await tick(SUGGESTION_DEBOUNCE + 50);
    // The empty field asks once on its own; that answer is not what these scenarios are about.
    apollo.match(SearchSeriesByPrefixDocument).forEach(op => op.flushData({ searchSeriesByPrefix: [] }));
    await settle();
  });

  async function settle() {
    await tick();
    await fixture.whenStable();
  }

  const input = () => (fixture.nativeElement as HTMLElement).querySelector('input')!;

  async function type(text: string) {
    input().value = text;
    input().dispatchEvent(new Event('input'));
    await settle();
  }

  async function suggest(...names: string[]) {
    await tick(SUGGESTION_DEBOUNCE + 50);
    const op = apollo.expectOne(SearchSeriesByPrefixDocument);
    op.flushData({ searchSeriesByPrefix: names });
    await settle();
    return op.operation.variables;
  }

  const offered = async () => {
    await autocomplete.focus();
    const options = await autocomplete.getOptions();
    return Promise.all(options.map(o => o.getText()));
  };

  it('suggests series matching what the user typed, once typing pauses', async () => {
    /*
      Given the user types "sa" then "sag" quickly
      Then only one search, for "sag", is sent once typing pauses
      When the backend returns "Saga" and "Sagas"
      Then both are suggested
    */
    await type('sa');
    await type('sag');

    expect(await suggest('Saga', 'Sagas')).toEqual({ prefix: 'sag', limit: 10 });
    expect(await offered()).toEqual(['Saga', 'Sagas']);
  });

  it('tells a picked series apart from a typed name', async () => {
    /*
      Given the suggestions include "Saga"
      When the user types "Sag"
      Then the value is "Sag" and nothing is reported as picked
      When the user picks "Saga"
      Then the value is "Saga" and "Saga" is reported as picked
    */
    await type('Sag');
    await suggest('Saga');
    expect(fixture.componentInstance.value()).toBe('Sag');
    expect(picked).toEqual([]);

    await autocomplete.focus();
    await autocomplete.selectOption({ text: 'Saga' });
    await settle();

    expect(fixture.componentInstance.value()).toBe('Saga');
    expect(picked).toEqual(['Saga']);
  });

  it('says when no series matches', async () => {
    /*
      Given the user types "zzz" and no series matches
      Then the suggestions say a new series can be created
    */
    await type('zzz');
    await suggest();

    expect(await offered()).toEqual(['No series matched — type to create a new one']);
  });
});
