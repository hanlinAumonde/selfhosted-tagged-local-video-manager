import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatAutocompleteHarness } from '@angular/material/autocomplete/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MatRadioButtonHarness } from '@angular/material/radio/testing';
import { MatSlideToggleHarness } from '@angular/material/slide-toggle/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';
import { MockInstance } from 'vitest';

import { VideoEditPanel } from './video-edit-panel';
import { EditableVideo, VideoEditPanelData } from '../../models/panels.model';
import { ToastType } from '../../models/toast.model';
import { ToastService } from '../../../services/toast-service/toast.service';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import {
  GetSeriesVideosDocument,
  SearchSeriesByPrefixDocument,
  UpdateVideoMetadataDocument,
} from '../../../core/graphql/generated/graphql';
import { aBrowseNode } from '../../../../testing/video-fixtures';
import { apolloAsInTheApp } from '../../../../testing/apollo-testing';

/** Apollo hands results to subscribers asynchronously. */
const tick = (ms = 0) => new Promise<void>(resolve => setTimeout(resolve, ms));
/** The series name field waits this long after typing before it asks for suggestions. */
const SUGGESTION_DEBOUNCE = 300;

const aVideo = (overrides: Parameters<typeof aBrowseNode>[0] = {}): EditableVideo =>
  aBrowseNode({ id: 'v1', name: 'Trip', author: 'bob', ...overrides }).node;
const withTags = (...names: string[]) => names.map(name => ({ __typename: 'VideoTag' as const, name }));
const member = (id: string, seriesOrder: number) =>
  ({ __typename: 'Video', id, name: id, seriesOrder, thumbnail: null, duration: 60, isLocked: false });
const inSaga = () => aVideo({ seriesName: 'Saga', seriesOrder: 2 });

describe('VideoEditPanel', () => {
  let fixture: ComponentFixture<VideoEditPanel>;
  let loader: HarnessLoader;
  let apollo: ApolloTestingController;
  let close: ReturnType<typeof vi.fn>;
  let toast: MockInstance<ToastService['emitNewToast']>;
  let announced: MockInstance<VideoUpdateEventService['emitUpdated']>;

  async function openPanel(data: VideoEditPanelData) {
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [VideoEditPanel, ApolloTestingModule],
      providers: [
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
    announced = vi.spyOn(TestBed.inject(VideoUpdateEventService), 'emitUpdated').mockImplementation(() => {});

    fixture = TestBed.createComponent(VideoEditPanel);
    loader = TestbedHarnessEnvironment.loader(fixture);
    await settle();
  }

  const editVideo = (video: EditableVideo) => openPanel({ mode: 'full', video });

  async function settle() {
    await tick();
    await fixture.whenStable();
  }

  // ─── Page reading and interaction ──────────────────────────────────

  const element = () => fixture.nativeElement as HTMLElement;
  const text = () => element().textContent!.replace(/\s+/g, ' ');
  const field = (placeholder: string) =>
    element().querySelector<HTMLInputElement>(`[placeholder="${placeholder}"]`);
  // The tag field shares the creator field's placeholder.
  const creatorField = () => [...element().querySelectorAll<HTMLInputElement>('input[placeholder="search"]')]
    .find(input => !input.closest('app-tag-chip-input'))!;
  const tagField = () => element().querySelector<HTMLInputElement>('app-tag-chip-input input')!;

  async function typeInto(input: HTMLInputElement | HTMLTextAreaElement, value: string) {
    input.value = value;
    input.dispatchEvent(new Event('input'));
    await settle();
  }

  async function addTag(tag: string) {
    await typeInto(tagField(), tag);
    tagField().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();
  }

  const chips = () => [...element().querySelectorAll('mat-chip')].map(chip => chip.textContent!.replace('cancel', '').trim());
  const lovedIcon = () => element().querySelector('#edit-loved mat-icon')!;

  const button = (label: RegExp) => loader.getHarness(MatButtonHarness.with({ text: label }));
  const SAVE = /^(Save|Saving\.\.\.|Apply Filter)$/;
  const isEnabled = async (label: RegExp) => !(await (await button(label)).isDisabled());

  async function press(label: RegExp) {
    await (await button(label)).click();
    await settle();
  }

  async function toggleModifySeries() {
    await (await loader.getHarness(MatSlideToggleHarness.with({ label: /Modify series/ }))).toggle();
    await settle();
  }

  const seriesNameField = () => field('Search or type a new series name') as HTMLInputElement;
  const listed = () =>
    [...element().querySelectorAll('app-series-reorder-list li')].map(li => li.querySelector('span.flex-1')!.textContent!.trim());
  const movable = () =>
    [...element().querySelectorAll('app-series-reorder-list li')]
      .filter(li => [...li.querySelectorAll('button')].some(b => !b.disabled))
      .map(li => li.querySelector('span.flex-1')!.textContent!.trim());

  async function moveCurrentVideoUp() {
    const row = [...element().querySelectorAll('app-series-reorder-list li')]
      .find(li => li.textContent!.includes('Current Video'))!;
    row.querySelector<HTMLButtonElement>('button[aria-label="Move up"]')!.click();
    await settle();
  }

  // ─── Backend answers ───────────────────────────────────────────────

  async function answerMembers(series: string, ...members: ReturnType<typeof member>[]) {
    const [op, ...others] = apollo.match(GetSeriesVideosDocument).filter(op => op.operation.variables['name'] === series);
    expect(others).toHaveLength(0);
    op.flushData({ getSeriesVideos: members });
    await settle();
  }

  async function pickSeriesSuggestion(typed: string, suggestion: string) {
    const autocomplete = await loader.getHarness(MatAutocompleteHarness.with({ ancestor: 'app-series-name-input' }));
    await autocomplete.enterText(typed);
    await tick(SUGGESTION_DEBOUNCE + 50);
    apollo.match(SearchSeriesByPrefixDocument)
      .filter(op => op.operation.variables['prefix'] === typed)
      .forEach(op => op.flushData({ searchSeriesByPrefix: [suggestion] }));
    await settle();
    await autocomplete.selectOption({ text: suggestion });
    await settle();
  }

  /** Saves and returns the update that was sent, still waiting for its answer. */
  async function save() {
    await press(SAVE);
    return apollo.expectOne(UpdateVideoMetadataDocument);
  }

  const sentInput = async () => (await save()).operation.variables['input'];

  async function answerUpdate(op: Awaited<ReturnType<typeof save>>, success: boolean) {
    const video = success
      ? { __typename: 'Video', id: 'v1', name: 'Trip 2', author: 'Unknown', loved: true, introduction: '', seriesName: null, seriesOrder: null, tags: [] }
      : null;
    op.flushData({ updateVideoMetadata: { __typename: 'VideoMutationResult', success, video } });
    await settle();
    return video;
  }

  // ─── Scenarios ─────────────────────────────────────────────────────

  describe('editing a video', () => {
    it('shows the video as it is now', async () => {
      /*
        Given video "v1" titled "Trip" by "bob", loved, introduced as "Holiday", tagged "travel", 2nd in series "Saga"
        When the panel is opened to edit it
        Then those details are filled in and it says the video is currently in "Saga" (order 2)
      */
      await editVideo(aVideo({ loved: true, introduction: 'Holiday', tags: withTags('travel'), seriesName: 'Saga', seriesOrder: 2 }));

      expect(text()).toContain('Edit video metadata');
      expect(field('Title-video')!.value).toBe('Trip');
      expect(creatorField().value).toBe('bob');
      expect(field('Enter introduction')!.value).toBe('Holiday');
      expect(lovedIcon().textContent!.trim()).toBe('favorite');
      expect(chips()).toEqual(['travel']);
      expect(text()).toContain('Currently in: Saga (order 2)');
    });

    it('saves the edited details and announces the video', async () => {
      /*
        Given the panel is editing video "v1" titled "Trip" by "bob", not loved, tagged "travel"
        When the user retitles it "Trip 2", erases the creator, marks it loved, adds tag "beach" and saves
        Then the update for "v1" carries title "Trip 2", creator "Unknown", loved, tags "travel" and "beach" and no series
        And "v1" is announced as updated, a success toast is shown and the panel closes with the saved video
      */
      await editVideo(aVideo({ tags: withTags('travel') }));

      await typeInto(field('Title-video')!, 'Trip 2');
      await typeInto(creatorField(), '');
      (lovedIcon() as HTMLElement).click();
      await addTag('beach');
      const op = await save();

      expect(op.operation.variables['input']).toEqual({
        videoId: 'v1', name: 'Trip 2', introduction: '', tags: ['travel', 'beach'], author: 'Unknown', loved: true,
      });
      const saved = await answerUpdate(op, true);
      expect(announced).toHaveBeenCalledExactlyOnceWith(['v1']);
      expect(toast).toHaveBeenCalledExactlyOnceWith('Video information updated successfully.', ToastType.Success);
      expect(close).toHaveBeenCalledExactlyOnceWith({ success: true, video: saved });
    });

    it('requires a title', async () => {
      /*
        Given the panel is editing video "v1"
        When the user erases the title
        Then "Save" is disabled
      */
      await editVideo(aVideo());
      expect(await isEnabled(SAVE)).toBe(true);

      await typeInto(field('Title-video')!, '');

      expect(await isEnabled(SAVE)).toBe(false);
    });

    it('stays open when the update fails', async () => {
      /*
        Given the panel is editing video "v1"
        When the user saves and the backend reports the update did not succeed
        Then an error toast is shown, nothing is announced and the panel stays open with "Save" enabled
      */
      await editVideo(aVideo());

      await answerUpdate(await save(), false);

      expect(toast).toHaveBeenCalledExactlyOnceWith('Failed to update video metadata.', ToastType.Error);
      expect(announced).not.toHaveBeenCalled();
      expect(close).not.toHaveBeenCalled();
      expect(await isEnabled(SAVE)).toBe(true);
    });
  });

  describe('changing the series', () => {
    it('moves the video within its series', async () => {
      /*
        Given video "v1" is 2nd in series "Saga" after "a" and before "c"
        When the user turns on "Modify series"
        Then the members of "Saga" are listed "a", the current video, "c", and only the current video can move
        When the user moves the current video up and saves
        Then the update sets series "Saga" with the order v1=1, a=2, c=3
        And "v1", "a" and "c" are all announced as updated
      */
      await editVideo(inSaga());

      await toggleModifySeries();
      await answerMembers('Saga', member('c', 3), member('v1', 2), member('a', 1));
      expect(listed()).toEqual(['a', 'Current Video', 'c']);
      expect(movable()).toEqual(['Current Video']);

      await moveCurrentVideoUp();
      const op = await save();
      expect(op.operation.variables['input'].series).toEqual({
        clear: false,
        name: 'Saga',
        orders: [{ videoId: 'v1', order: 1 }, { videoId: 'a', order: 2 }, { videoId: 'c', order: 3 }],
      });

      await answerUpdate(op, true);
      expect(announced).toHaveBeenCalledExactlyOnceWith(['v1', 'a', 'c']);
    });

    it('joins a series picked from the suggestions, at its end', async () => {
      /*
        Given video "v1" is in no series
        When the user turns on "Modify series"
        Then only the current video is listed
        When the user types "Ep" and picks the suggestion "Epic", whose members are "x" then "y"
        Then "x", "y" and the current video are listed
        When the user saves
        Then the update sets series "Epic" with the order x=1, y=2, v1=3
      */
      await editVideo(aVideo());

      await toggleModifySeries();
      expect(listed()).toEqual(['Current Video']);

      await pickSeriesSuggestion('Ep', 'Epic');
      await answerMembers('Epic', member('y', 2), member('x', 1));
      expect(listed()).toEqual(['x', 'y', 'Current Video']);

      expect((await sentInput()).series).toEqual({
        clear: false,
        name: 'Epic',
        orders: [{ videoId: 'x', order: 1 }, { videoId: 'y', order: 2 }, { videoId: 'v1', order: 3 }],
      });
    });

    it('starts a new series when a name is typed rather than picked', async () => {
      /*
        Given video "v1" is 2nd in series "Saga" and its members are listed
        When the user types the series name "Fresh"
        Then only the current video is listed
        When the user saves
        Then the update sets series "Fresh" with only v1=1
      */
      await editVideo(inSaga());
      await toggleModifySeries();
      await answerMembers('Saga', member('a', 1), member('v1', 2));

      await typeInto(seriesNameField(), 'Fresh');
      expect(listed()).toEqual(['Current Video']);

      expect((await sentInput()).series).toEqual({ clear: false, name: 'Fresh', orders: [{ videoId: 'v1', order: 1 }] });
    });

    it('ignores the members of a series the user has already moved away from', async () => {
      /*
        Given video "v1" is 2nd in series "Saga"
        When the user turns on "Modify series" and types "Fresh" before the members of "Saga" arrive
        And the members of "Saga" then arrive
        Then only the current video is listed
        When the user saves
        Then the update sets series "Fresh" with only v1=1
      */
      await editVideo(inSaga());
      await toggleModifySeries();

      await typeInto(seriesNameField(), 'Fresh');
      await answerMembers('Saga', member('a', 1), member('v1', 2));
      expect(listed()).toEqual(['Current Video']);

      expect((await sentInput()).series).toEqual({ clear: false, name: 'Fresh', orders: [{ videoId: 'v1', order: 1 }] });
    });

    it('removes the video from its series', async () => {
      /*
        Given video "v1" is in series "Saga"
        When the user turns on "Modify series", chooses "Clear" and saves
        Then the update clears the series
      */
      await editVideo(inSaga());
      await toggleModifySeries();

      await (await loader.getHarness(MatRadioButtonHarness.with({ label: /Clear/ }))).check();
      await settle();
      expect(text()).toContain('This video will be removed from its current series on save.');

      expect((await sentInput()).series).toEqual({ clear: true });
    });

    it('leaves the series untouched once "Modify series" is turned off again', async () => {
      /*
        Given video "v1" is in series "Saga"
        When the user turns on "Modify series", types "Fresh" and turns it off again
        Then it says the video is currently in "Saga"
        When the user saves
        Then the update carries no series
        When the user turns on "Modify series" once more
        Then the series name is "Saga" again
      */
      await editVideo(inSaga());
      await toggleModifySeries();
      await typeInto(seriesNameField(), 'Fresh');

      await toggleModifySeries();
      expect(text()).toContain('Currently in: Saga');

      expect((await sentInput()).series).toBeUndefined();

      await toggleModifySeries();
      expect(seriesNameField().value).toBe('Saga');
    });
  });

  describe('choosing tags for a filter', () => {
    it('collects tags only and hands them back', async () => {
      /*
        Given the panel is opened to filter by tags with "a" already chosen
        Then only the tags field is shown
        When the user adds tag "b" and applies the filter
        Then the panel closes with tags "a" and "b" and nothing is sent to the backend
      */
      await openPanel({ mode: 'filter', selectedTags: ['a'] });
      expect(text()).toContain('Filter tags');
      expect(field('Title-video')).toBeNull();
      expect(chips()).toEqual(['a']);

      await addTag('b');
      await press(SAVE);

      expect(close).toHaveBeenCalledExactlyOnceWith(['a', 'b']);
      apollo.expectNone(UpdateVideoMetadataDocument);
    });
  });

  it('closes without saving on cancel', async () => {
    /*
      Given the panel is editing video "v1"
      When the user cancels
      Then the panel closes with nothing and no update is sent
    */
    await editVideo(aVideo());

    await press(/Cancel/);

    expect(close).toHaveBeenCalledExactlyOnceWith();
    apollo.expectNone(UpdateVideoMetadataDocument);
  });
});
