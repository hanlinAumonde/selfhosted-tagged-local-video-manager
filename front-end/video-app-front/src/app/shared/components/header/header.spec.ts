import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatButtonHarness } from '@angular/material/button/testing';

import { Header } from './header';
import { ThemeService } from '../../../services/theme-service/theme.service';

describe('Header', () => {
  let fixture: ComponentFixture<Header>;

  beforeEach(async () => {
    localStorage.setItem('app-theme', 'light');
    fixture = TestBed.createComponent(Header);
    await fixture.whenStable();
  });

  afterEach(() => localStorage.clear());

  const text = () => (fixture.nativeElement as HTMLElement).textContent!.replace(/\s+/g, ' ');

  it('shows the page title', async () => {
    /*
      Given the title is "File Browser"
      Then the header shows "File Browser"
    */
    fixture.componentRef.setInput('title', 'File Browser');
    await fixture.whenStable();

    expect((fixture.nativeElement as HTMLElement).querySelector('h1')!.textContent).toBe('File Browser');
  });

  it('switches between the light and the dark theme', async () => {
    /*
      Given the light theme is on
      Then the toggle offers the dark mode
      When the user clicks the toggle
      Then the dark theme is on and the toggle offers the light mode
    */
    expect(text()).toContain('dark_mode');

    await (await TestbedHarnessEnvironment.loader(fixture).getHarness(MatButtonHarness)).click();

    expect(TestBed.inject(ThemeService).isDark()).toBe(true);
    expect(text()).toContain('light_mode');
  });
});
