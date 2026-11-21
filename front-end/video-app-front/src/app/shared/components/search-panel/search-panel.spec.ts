import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { ApolloTestingModule } from 'apollo-angular/testing';

import { SearchPanel } from './search-panel';
import { environment } from '../../../../environments/environment';

/** Apollo hands results to subscribers asynchronously. */
const tick = () => new Promise<void>(resolve => setTimeout(resolve));

describe('SearchPanel', () => {
  let fixture: ComponentFixture<SearchPanel>;
  let loader: HarnessLoader;
  let close: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [SearchPanel, ApolloTestingModule],
      providers: [
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { directoryPath: 'local/movies' } },
      ],
    });
    fixture = TestBed.createComponent(SearchPanel);
    loader = TestbedHarnessEnvironment.loader(fixture);
    await settle();
  });

  /** Material shows a field's error only once the field has been left. */
  async function leave(input: HTMLInputElement) {
    input.dispatchEvent(new Event('blur'));
    await settle();
  }

  async function settle() {
    await tick();
    await fixture.whenStable();
  }

  const element = () => fixture.nativeElement as HTMLElement;
  const field = (placeholder: string) => element().querySelector<HTMLInputElement>(`input[placeholder="${placeholder}"]`)!;
  const searchButton = () => loader.getHarness(MatButtonHarness.with({ text: 'Search' }));
  const canSearch = async () => !(await (await searchButton()).isDisabled());

  async function type(placeholder: string, value: string) {
    field(placeholder).value = value;
    field(placeholder).dispatchEvent(new Event('input'));
    await settle();
  }

  const typeName = (value: string) => type('Part of the video name', value);
  const typeAuthor = (value: string) => type('Part of the author name', value);

  async function addTag(tag: string) {
    await type('A video must carry every tag listed', tag);
    field('A video must carry every tag listed').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
  }

  it('says which directory it searches', () => {
    /*
      Given the panel is opened for "local/movies"
      Then it says it searches "local/movies" and everything below it
    */
    expect(element().textContent!.replace(/\s+/g, ' ')).toContain('Searches local/movies and everything below it.');
  });

  it('cannot search while every field is blank', async () => {
    /*
      Given the panel is open
      Then "Search" is disabled
      When the user types only spaces as the name and the author
      Then "Search" is still disabled
      When the user adds tag "travel"
      Then "Search" is enabled
    */
    expect(await canSearch()).toBe(false);

    await typeName('   ');
    await typeAuthor('   ');
    expect(await canSearch()).toBe(false);

    await addTag('travel');
    expect(await canSearch()).toBe(true);
  });

  it('hands back the trimmed criteria', async () => {
    /*
      Given the panel is open
      When the user types the name " trip ", the author " bob ", adds tag "travel" and searches
      Then the panel closes with name "trip", author "bob" and tags "travel"
    */
    await typeName(' trip ');
    await typeAuthor(' bob ');
    await addTag('travel');

    await (await searchButton()).click();
    await settle();

    expect(close).toHaveBeenCalledExactlyOnceWith({ name: 'trip', author: 'bob', tags: ['travel'] });
  });

  it('refuses a name longer than allowed', async () => {
    /*
      Given the panel is open
      When the user types a name one character longer than allowed and leaves the field
      Then an error says the maximum length and "Search" is disabled
    */
    const max = environment.VALIDATION_RULES.NAME_MAX_LENGTH;

    await typeName('a'.repeat(max + 1));
    await leave(field('Part of the video name'));

    expect(element().querySelector('mat-error')!.textContent).toContain(`Maximum length is ${max} characters`);
    expect(await canSearch()).toBe(false);
  });
});
