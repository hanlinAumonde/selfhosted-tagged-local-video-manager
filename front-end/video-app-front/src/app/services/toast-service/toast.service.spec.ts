import { TestBed } from '@angular/core/testing';

import { ToastService } from './toast.service';
import { ToastType } from '../../shared/models/toast.model';
import { environment } from '../../../environments/environment';

const { MAX_TOASTS, AUTO_DISMISS_MS, EXIT_ANIMATION_MS } = environment.ERROR_TOAST_SETTINGS;

describe('ToastService', () => {
  let toasts: ToastService;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({});
    toasts = TestBed.inject(ToastService);
  });

  afterEach(() => vi.useRealTimers());

  const emit = (...messages: string[]) => messages.forEach(m => toasts.emitNewToast(m, ToastType.Error));
  const idOf = (message: string) => toasts.toasts().find(t => t.message === message)!.id;
  /** The listed toasts by message, with the ones playing their exit animation marked. */
  const shown = () => toasts.toasts().map(t => (t.removing ? `${t.message} (leaving)` : t.message));

  it('shows each new toast with its own id, message and type', () => {
    /*
      Given no toast is shown
      When an error toast "a" and a success toast "b" are emitted
      Then both are listed in that order with different ids, their messages and types
      And neither is leaving
    */
    toasts.emitNewToast('a', ToastType.Error);
    toasts.emitNewToast('b', ToastType.Success);

    const [a, b] = toasts.toasts();
    expect(a).toMatchObject({ message: 'a', type: ToastType.Error });
    expect(b).toMatchObject({ message: 'b', type: ToastType.Success });
    expect(a.id).not.toBe(b.id);
    expect(shown()).toEqual(['a', 'b']);
  });

  it('lets a toast leave on its own after the auto-dismiss delay', () => {
    /*
      Given an error toast "a" was emitted, and a warning toast "b" 5 seconds later
      When just under 10 seconds have passed since "a"
      Then "a" is still shown and not leaving
      When 10 seconds have passed since "a"
      Then "a" is leaving but still listed, so its exit animation can play
      And "b" is untouched
      When the 300ms exit animation has also passed
      Then only "b" is listed
    */
    toasts.emitNewToast('a', ToastType.Error);
    vi.advanceTimersByTime(5000);
    toasts.emitNewToast('b', ToastType.Warning);

    vi.advanceTimersByTime(AUTO_DISMISS_MS - 5000 - 1);
    expect(shown()).toEqual(['a', 'b']);

    vi.advanceTimersByTime(1);
    expect(shown()).toEqual(['a (leaving)', 'b']);

    vi.advanceTimersByTime(EXIT_ANIMATION_MS);
    expect(shown()).toEqual(['b']);
  });

  it('removes a dismissed toast once its exit animation has played', () => {
    /*
      Given toasts "a", "b" and "c" are shown
      When "b" is dismissed
      Then "b" is immediately marked as leaving and the others are untouched
      When 300ms pass
      Then only "a" and "c" are listed
    */
    emit('a', 'b', 'c');

    toasts.dismiss(idOf('b'));
    expect(shown()).toEqual(['a', 'b (leaving)', 'c']);

    vi.advanceTimersByTime(EXIT_ANIMATION_MS);
    expect(shown()).toEqual(['a', 'c']);
  });

  it('pushes out the oldest toast when one more than the limit is shown', () => {
    /*
      Given 4 toasts "a" to "d" are shown, the most allowed
      When toast "e" is emitted
      Then "a" is marked as leaving and the others are untouched
      When 300ms pass
      Then "b", "c", "d" and "e" are listed
    */
    expect(MAX_TOASTS).toBe(4);
    emit('a', 'b', 'c', 'd');

    emit('e');
    expect(shown()).toEqual(['a (leaving)', 'b', 'c', 'd', 'e']);

    vi.advanceTimersByTime(EXIT_ANIMATION_MS);
    expect(shown()).toEqual(['b', 'c', 'd', 'e']);
  });

  it('pushes out the oldest toast that is not already leaving', () => {
    /*
      Given 4 toasts "a" to "d" are shown and "a" has just been dismissed
      When toast "e" is emitted
      Then "b" is marked as leaving as well
      When 300ms pass
      Then "c", "d" and "e" are listed
    */
    emit('a', 'b', 'c', 'd');
    toasts.dismiss(idOf('a'));

    emit('e');
    expect(shown()).toEqual(['a (leaving)', 'b (leaving)', 'c', 'd', 'e']);

    vi.advanceTimersByTime(EXIT_ANIMATION_MS);
    expect(shown()).toEqual(['c', 'd', 'e']);
  });

  it('clears every toast at once', () => {
    /*
      Given toasts "a", "b" and "c" are shown and "b" is leaving
      When all toasts are cleared
      Then no toast is listed
    */
    emit('a', 'b', 'c');
    toasts.dismiss(idOf('b'));

    toasts.clearAllToasts();

    expect(shown()).toEqual([]);
  });
});
