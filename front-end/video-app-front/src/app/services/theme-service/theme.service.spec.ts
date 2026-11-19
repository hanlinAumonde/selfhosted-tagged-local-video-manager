import { TestBed } from '@angular/core/testing';

import { ThemeService } from './theme.service';

const STORAGE_KEY = 'app-theme';
const root = document.documentElement;

describe('ThemeService', () => {
  afterEach(() => {
    localStorage.clear();
    root.classList.remove('dark');
    root.style.colorScheme = '';
    vi.restoreAllMocks();
  });

  /** A fresh app start with the given saved choice and system preference. */
  function startApp(saved: 'dark' | 'light' | null, systemPrefersDark: boolean): ThemeService {
    TestBed.resetTestingModule();
    localStorage.clear();
    if (saved) localStorage.setItem(STORAGE_KEY, saved);
    vi.spyOn(window, 'matchMedia').mockImplementation(
      query => ({ matches: systemPrefersDark && query === '(prefers-color-scheme: dark)', media: query }) as MediaQueryList,
    );
    const theme = TestBed.inject(ThemeService);
    TestBed.tick();
    return theme;
  }

  const page = () => ({
    dark: root.classList.contains('dark'),
    colorScheme: root.style.colorScheme,
    saved: localStorage.getItem(STORAGE_KEY),
  });

  describe('initial theme', () => {
    it('uses a saved choice over the system preference', () => {
      /*
        Given "dark" was saved and the system prefers light
        When the app starts
        Then the theme is dark
        Given instead "light" was saved and the system prefers dark
        When the app starts
        Then the theme is light
      */
      expect(startApp('dark', false).isDark()).toBe(true);
      expect(startApp('light', true).isDark()).toBe(false);
    });

    it('follows the system preference when nothing was saved', () => {
      /*
        Given nothing was saved and the system prefers dark
        When the app starts
        Then the theme is dark
        Given instead nothing was saved and the system prefers light
        When the app starts
        Then the theme is light
      */
      expect(startApp(null, true).isDark()).toBe(true);
      expect(startApp(null, false).isDark()).toBe(false);
    });

    it('applies and saves the starting theme', () => {
      /*
        Given nothing was saved and the system prefers dark
        When the app starts
        Then the page root has the "dark" class and a dark color scheme
        And "dark" is saved
      */
      startApp(null, true);

      expect(page()).toEqual({ dark: true, colorScheme: 'dark', saved: 'dark' });
    });
  });

  describe('toggle', () => {
    it('switches the page between dark and light and saves each choice', () => {
      /*
        Given the app started in the dark theme
        When the theme is toggled
        Then the page root loses the "dark" class, has a light color scheme, and "light" is saved
        When the theme is toggled again
        Then the page root has the "dark" class, a dark color scheme, and "dark" is saved
      */
      const theme = startApp('dark', false);

      theme.toggle();
      TestBed.tick();
      expect(page()).toEqual({ dark: false, colorScheme: 'light', saved: 'light' });

      theme.toggle();
      TestBed.tick();
      expect(page()).toEqual({ dark: true, colorScheme: 'dark', saved: 'dark' });
    });
  });
});
