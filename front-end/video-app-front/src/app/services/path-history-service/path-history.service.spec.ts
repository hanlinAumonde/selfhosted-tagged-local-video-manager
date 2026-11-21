import { TestBed } from '@angular/core/testing';

import { PathHistoryService } from './path-history.service';

describe('PathHistoryService', () => {
  let history: PathHistoryService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    history = TestBed.inject(PathHistoryService);
  });

  const open = (...paths: string[][]) => paths.forEach(path => history.pushNewPath(path));
  const back = () => history.popHisotryPath();
  const forward = () => history.pushForwardPath();

  describe('back and forward', () => {
    it('steps back one directory at a time until the root', () => {
      /*
        Given the user opened "A", then "A/B", then "A/B/C" from the root
        When back is pressed three times
        Then it returns "A/B", then "A", then nothing (the root)
        And there is no more history to go back to
      */
      open(['A'], ['A', 'B'], ['A', 'B', 'C']);

      expect([back(), back(), back()]).toEqual([['A', 'B'], ['A'], undefined]);
      expect(history.hasHistory()).toBe(false);
    });

    it('retraces the same directories going forward', () => {
      /*
        Given the user opened "A" and "A/B" and then went back twice to the root
        When forward is pressed twice
        Then it returns "A", then "A/B"
        And there is nothing left to go forward to
      */
      open(['A'], ['A', 'B']);
      back();
      back();

      expect([forward(), forward()]).toEqual([['A'], ['A', 'B']]);
      expect(history.hasForward()).toBe(false);
    });

    it('discards the forward steps when the user opens a new directory', () => {
      /*
        Given the user opened "A" and "A/B" and went back to "A"
        When the user opens "A/D"
        Then there is nothing to go forward to
        And back returns "A"
      */
      open(['A'], ['A', 'B']);
      back();

      open(['A', 'D']);

      expect(history.hasForward()).toBe(false);
      expect(back()).toEqual(['A']);
    });

    it('records a breadcrumb jump as a new step', () => {
      /*
        Given the user opened "A", "A/B" and "A/B/C"
        When the user jumps to "A" through the breadcrumb
        Then back returns "A/B/C"
      */
      open(['A'], ['A', 'B'], ['A', 'B', 'C']);

      open(['A']);

      expect(back()).toEqual(['A', 'B', 'C']);
    });

    it('changes nothing when there is nowhere to go', () => {
      /*
        Given the user opened "A" only
        When forward is pressed
        Then it returns "A" and there is still nothing to go forward to
        When back is pressed twice
        Then the second press returns nothing and there is still exactly one forward step
      */
      open(['A']);

      expect(forward()).toEqual(['A']);
      expect(history.hasForward()).toBe(false);

      back();
      expect(back()).toBeUndefined();
      expect(forward()).toEqual(['A']);
      expect(history.hasForward()).toBe(false);
    });

    it('is not affected by callers changing the paths they passed in or got back', () => {
      /*
        Given the user opened "A" and "A/B" using an array the caller later changes to "X/Y"
        And back returned "A", which the caller then changes to "Z"
        When forward and back are pressed
        Then they return "A/B" and "A"
      */
      const path = ['A'];
      open(path);
      path.push('B');
      open(path);
      path.splice(0, path.length, 'X', 'Y');

      const returned = back()!;
      returned.splice(0, returned.length, 'Z');

      expect(forward()).toEqual(['A', 'B']);
      expect(back()).toEqual(['A']);
    });
  });

  describe('scroll positions', () => {
    it('remembers the last position left in each directory', () => {
      /*
        Given the user left "A" at 300, "A/B" at 120, and later left "A" again at 50
        Then the position for "A" is 50 and for "A/B" is 120
        And a directory never left starts at the top
      */
      history.rememberScroll(['A'], 300);
      history.rememberScroll(['A', 'B'], 120);
      history.rememberScroll(['A'], 50);

      expect(history.scrollOf(['A'])).toBe(50);
      expect(history.scrollOf(['A', 'B'])).toBe(120);
      expect(history.scrollOf(['A', 'C'])).toBe(0);
    });
  });

  describe('clearAllHistory', () => {
    it('forgets every step and every scroll position', () => {
      /*
        Given the user opened "A" and "A/B", went back once, and left "A" at 300
        When the history is cleared
        Then there is nothing to go back or forward to
        And "A" starts at the top
      */
      open(['A'], ['A', 'B']);
      back();
      history.rememberScroll(['A'], 300);

      history.clearAllHistory();

      expect(history.hasHistory()).toBe(false);
      expect(history.hasForward()).toBe(false);
      expect(history.scrollOf(['A'])).toBe(0);
    });
  });
});
