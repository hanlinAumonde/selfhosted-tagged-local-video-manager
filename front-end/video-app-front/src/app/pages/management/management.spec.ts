import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatTabGroupHarness } from '@angular/material/tabs/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';

import { Management } from './management';
import { MigrationTaskList } from '../../shared/components/migration-task-list/migration-task-list';

/** The task list has its own spec; here it only needs to be there or not. */
@Component({ selector: 'app-migration-task-list', template: 'migration tasks' })
class TaskListStandIn {}

describe('Management', () => {
  let fixture: ComponentFixture<Management>;

  beforeEach(async () => {
    TestBed.overrideComponent(Management, { remove: { imports: [MigrationTaskList] }, add: { imports: [TaskListStandIn] } });
    // A tab's lazy content waits for its slide-in to finish, which never happens without a layout.
    TestBed.configureTestingModule({ providers: [{ provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } }] });
    fixture = TestBed.createComponent(Management);
    await fixture.whenStable();
  });

  const tabs = () => TestbedHarnessEnvironment.loader(fixture).getHarness(MatTabGroupHarness);
  const element = () => fixture.nativeElement as HTMLElement;

  it('opens on the migration tasks', async () => {
    /*
      Given the management page is opened
      Then the "Tasks" tab is selected with "Migration" highlighted
      And the migration task list is shown
    */
    expect(await (await (await tabs()).getSelectedTab()).getLabel()).toBe('Tasks');
    const migration = [...element().querySelectorAll('nav button')].find(b => b.textContent!.includes('Migration'))!;
    expect(migration.classList).toContain('font-semibold');
    expect(element().textContent).toContain('migration tasks');
  });

  it('has a placeholder for settings', async () => {
    /*
      Given the management page is opened
      When the user selects the "Settings" tab
      Then it says "Settings coming soon"
    */
    await (await tabs()).selectTab({ label: 'Settings' });
    await fixture.whenStable();

    expect(element().textContent).toContain('Settings coming soon');
  });
});
