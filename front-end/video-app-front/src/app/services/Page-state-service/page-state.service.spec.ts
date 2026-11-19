import { TestBed } from '@angular/core/testing';

import { PageStateService } from './page-state.service';

const THIS_TAB = false;
const CROSS_TAB = true;

describe('PageStateService', () => {
  let state: PageStateService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    state = TestBed.inject(PageStateService);
  });

  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  describe('getState / setState', () => {
    it('hands a tab-only state back once', () => {
      /*
        Given a search state { page: 3, tags: ["4k"] } was saved for this tab under "search"
        When it is read
        Then the same state comes back
        And it is not visible to other tabs
        When it is read again
        Then nothing comes back
      */
      state.setState('search', { page: 3, tags: ['4k'] }, THIS_TAB);

      expect(state.getState('search', CROSS_TAB)).toBeUndefined();
      expect(state.getState('search', THIS_TAB)).toEqual({ page: 3, tags: ['4k'] });
      expect(state.getState('search', THIS_TAB)).toBeUndefined();
    });

    it('hands a cross-tab state back once', () => {
      /*
        Given a search state { tags: ["4k"] } was saved for other tabs under "search"
        When it is read as a cross-tab state
        Then the same state comes back
        When it is read again
        Then nothing comes back
      */
      state.setState('search', { tags: ['4k'] }, CROSS_TAB);

      expect(state.getState('search', CROSS_TAB)).toEqual({ tags: ['4k'] });
      expect(state.getState('search', CROSS_TAB)).toBeUndefined();
    });

    it('keeps tab-only and cross-tab states under the same key apart', () => {
      /*
        Given state "tab" was saved for this tab and state "shared" for other tabs, both under "search"
        When each is read
        Then the tab-only read returns "tab" and the cross-tab read returns "shared"
      */
      state.setState('search', 'tab', THIS_TAB);
      state.setState('search', 'shared', CROSS_TAB);

      expect(state.getState('search', THIS_TAB)).toBe('tab');
      expect(state.getState('search', CROSS_TAB)).toBe('shared');
    });

    it('returns nothing for a key never saved', () => {
      /*
        Given nothing was saved under "search"
        When it is read for this tab and as a cross-tab state
        Then nothing comes back either way
      */
      expect(state.getState('search', THIS_TAB)).toBeUndefined();
      expect(state.getState('search', CROSS_TAB)).toBeUndefined();
    });

    it('round-trips values that look empty', () => {
      /*
        Given 0, false, an empty string and an empty list were saved under four keys
        When each is read
        Then each comes back as saved rather than as nothing
      */
      const values = { zero: 0, no: false, blank: '', none: [] as string[] };
      for (const [key, value] of Object.entries(values)) state.setState(key, value, THIS_TAB);

      for (const [key, value] of Object.entries(values)) {
        expect(state.getState(key, THIS_TAB)).toEqual(value);
      }
    });
  });

  describe('clearing', () => {
    beforeEach(() => {
      state.setState('search', 'tab search', THIS_TAB);
      state.setState('browse', 'tab browse', THIS_TAB);
      state.setState('search', 'shared search', CROSS_TAB);
    });

    it('clears one key in one scope only', () => {
      /*
        Given states were saved under "search" and "browse" for this tab, and under "search" for other tabs
        When the tab-only "search" state is cleared
        Then the tab-only "search" read returns nothing
        And the tab-only "browse" and the cross-tab "search" states still come back
      */
      state.clearState('search', THIS_TAB);

      expect(state.getState('search', THIS_TAB)).toBeUndefined();
      expect(state.getState('browse', THIS_TAB)).toBe('tab browse');
      expect(state.getState('search', CROSS_TAB)).toBe('shared search');
    });

    it('clears every tab-only state but no cross-tab one', () => {
      /*
        Given states were saved under "search" and "browse" for this tab, and under "search" for other tabs
        When all tab-only states are cleared
        Then neither tab-only state comes back
        And the cross-tab "search" state still comes back
      */
      state.clearAllTabStates();

      expect(state.getState('search', THIS_TAB)).toBeUndefined();
      expect(state.getState('browse', THIS_TAB)).toBeUndefined();
      expect(state.getState('search', CROSS_TAB)).toBe('shared search');
    });
  });
});
