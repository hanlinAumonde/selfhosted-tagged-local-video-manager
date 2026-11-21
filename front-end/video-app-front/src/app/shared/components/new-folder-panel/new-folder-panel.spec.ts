import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { HarnessLoader } from '@angular/cdk/testing';
import { MatButtonHarness } from '@angular/material/button/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { ApolloTestingController, ApolloTestingModule, TestOperation } from 'apollo-angular/testing';
import { MockInstance } from 'vitest';

import { NewFolderPanel } from './new-folder-panel';
import { ToastType } from '../../models/toast.model';
import { ToastService } from '../../../services/toast-service/toast.service';
import { CreateDirectoryDocument } from '../../../core/graphql/generated/graphql';
import { apolloAsInTheApp } from '../../../../testing/apollo-testing';

/** Apollo hands results to subscribers asynchronously. */
const tick = () => new Promise<void>(resolve => setTimeout(resolve));

describe('NewFolderPanel', () => {
  let fixture: ComponentFixture<NewFolderPanel>;
  let loader: HarnessLoader;
  let apollo: ApolloTestingController;
  let close: ReturnType<typeof vi.fn>;
  let toast: MockInstance<ToastService['emitNewToast']>;

  async function openPanel(parentPath: string) {
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [NewFolderPanel, ApolloTestingModule],
      providers: [
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { parentPath } },
      ],
    });
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
    fixture = TestBed.createComponent(NewFolderPanel);
    loader = TestbedHarnessEnvironment.loader(fixture);
    await settle();
  }

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
  const text = () => element().textContent!.replace(/\s+/g, ' ');
  const nameField = () => element().querySelector<HTMLInputElement>('input')!;
  const isEnabled = async (label: string) =>
    !(await (await loader.getHarness(MatButtonHarness.with({ text: label }))).isDisabled());

  async function typeName(name: string) {
    nameField().value = name;
    nameField().dispatchEvent(new Event('input'));
    await settle();
  }

  async function create() {
    await (await loader.getHarness(MatButtonHarness.with({ text: 'Create' }))).click();
    await settle();
  }

  /** What Enter in the only field of a form does in a browser. */
  async function pressEnter() {
    element().querySelector('form')!.requestSubmit();
    await settle();
  }

  async function requested(name: string): Promise<TestOperation> {
    await typeName(name);
    await create();
    return apollo.expectOne(CreateDirectoryDocument);
  }

  it('says where the folder will be created', async () => {
    /*
      Given the panel is opened in "local/movies"
      Then it says the folder is created in "local/movies"
      Given instead it is opened at the root
      Then it says the folder is created in the current directory
    */
    await openPanel('local/movies');
    expect(text()).toContain('Created in local/movies');

    TestBed.resetTestingModule();
    await openPanel('');
    expect(text()).toContain('Created in the current directory');
  });

  it('only allows a valid folder name', async () => {
    /*
      Given the panel is open
      Then "Create" is disabled and no error is shown
      When the user types "a/b" and leaves the field
      Then an error says a folder name cannot contain "/" and "Create" is disabled
      When the user types "  Trips  "
      Then "Create" is enabled
    */
    await openPanel('local');
    expect(await isEnabled('Create')).toBe(false);
    expect(element().querySelector('mat-error')).toBeNull();

    await typeName('a/b');
    await leave(nameField());
    expect(element().querySelector('mat-error')!.textContent).toContain('cannot contain "/"');
    expect(await isEnabled('Create')).toBe(false);

    await typeName('  Trips  ');
    expect(await isEnabled('Create')).toBe(true);
  });

  it('creates the trimmed folder under the parent and closes', async () => {
    /*
      Given the panel is opened in "local/movies"
      When the user types "  Trips  " and clicks "Create"
      Then a folder "Trips" is requested in "local/movies" and both buttons are disabled while it is created
      When the backend reports folder "Trips" was created
      Then a toast says folder "Trips" was created and the panel closes reporting success
    */
    await openPanel('local/movies');

    const op = await requested('  Trips  ');
    expect(op.operation.variables['input']).toEqual({ parentPath: { relativePath: 'local/movies' }, name: 'Trips' });
    expect([await isEnabled('Create'), await isEnabled('Cancel')]).toEqual([false, false]);

    op.flushData({ createDirectory: { __typename: 'DirectoryMutationResult', success: true, name: 'Trips', path: 'local/movies/Trips' } });
    await settle();
    expect(toast).toHaveBeenCalledExactlyOnceWith('Folder "Trips" created.', ToastType.Success);
    expect(close).toHaveBeenCalledExactlyOnceWith(true);
  });

  it('creates the folder at the root without a parent path', async () => {
    /*
      Given the panel is opened at the root
      When the user creates folder "Trips"
      Then the request names no parent path
    */
    await openPanel('');

    const op = await requested('Trips');

    expect(op.operation.variables['input'].parentPath.relativePath).toBeUndefined();
  });

  it('creates the folder when the user presses Enter, but only for a valid name', async () => {
    /*
      Given the panel is open with the name "a/b"
      When the user presses Enter
      Then nothing is requested
      When the user types "Trips" and presses Enter
      Then folder "Trips" is requested
    */
    await openPanel('local');
    await typeName('a/b');

    await pressEnter();
    apollo.expectNone(CreateDirectoryDocument);

    await typeName('Trips');
    await pressEnter();
    expect(apollo.expectOne(CreateDirectoryDocument).operation.variables['input'].name).toBe('Trips');
  });

  it('stays open for another name when the backend refuses', async () => {
    /*
      Given the user has asked for folder "Trips"
      When the backend refuses because a folder of that name exists
      Then only the request's own error toast is shown
      And the panel stays open with "Create" enabled
    */
    await openPanel('local');
    const op = await requested('Trips');

    op.flush({ errors: [{ message: 'a folder named "Trips" already exists' }] });
    await settle();

    expect(toast).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('already exists'), ToastType.Error);
    expect(close).not.toHaveBeenCalled();
    expect(await isEnabled('Create')).toBe(true);
  });

  it('stays open when the folder was not created', async () => {
    /*
      Given the user has asked for folder "Trips"
      When the backend reports the folder was not created
      Then an error toast says the folder could not be created and the panel stays open
    */
    await openPanel('local');
    const op = await requested('Trips');

    op.flushData({ createDirectory: { __typename: 'DirectoryMutationResult', success: false, name: 'Trips', path: '' } });
    await settle();

    expect(toast).toHaveBeenCalledExactlyOnceWith('Failed to create the folder.', ToastType.Error);
    expect(close).not.toHaveBeenCalled();
  });
});
