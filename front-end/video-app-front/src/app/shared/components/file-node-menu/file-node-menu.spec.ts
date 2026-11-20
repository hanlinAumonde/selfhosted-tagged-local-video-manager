import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { MatMenuItemHarness } from '@angular/material/menu/testing';
import { MatMenuModule } from '@angular/material/menu';
import { MatDialog } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import { Subject } from 'rxjs';

import { FileNodeMenu } from './file-node-menu';
import { FileBrowseNode } from '../../models/GQL-result.model';
import { DeleteType } from '../../models/panels.model';
import { ToastService } from '../../../services/toast-service/toast.service';
import { ToastType } from '../../models/toast.model';
import { VideoEditPanel } from '../video-edit-panel/video-edit-panel';
import { DeleteCheckPanel } from '../delete-check-panel/delete-check-panel';
import { MigrationPanel } from '../migration-panel/migration-panel';
import { BatchOperationPanel } from '../batch-operation-panel/batch-operation-panel';
import { aBrowseNode } from '../../../../testing/video-fixtures';

@Component({
  imports: [FileNodeMenu, MatMenuModule],
  template: `
    <app-file-node-menu
      #m
      [item]="item()"
      [currentPath]="path()"
      (refreshDirectoryMeta)="refreshed.push($event.node.name)"
      (migrationResult)="migrations.push($event)"
      (batchSyncDirectoryResult)="syncs.push($event)"
    />
    <button id="open" [matMenuTriggerFor]="m.menu()!">open</button>
  `,
})
class MenuHost {
  item = signal<FileBrowseNode>(aBrowseNode());
  path = signal(['local', 'movies']);
  refreshed: string[] = [];
  migrations: boolean[] = [];
  syncs: boolean[] = [];
}

describe('FileNodeMenu', () => {
  let fixture: ComponentFixture<MenuHost>;
  let dialog: { open: ReturnType<typeof vi.fn> };
  let closed: Subject<unknown>;

  async function showMenuOf(item: FileBrowseNode) {
    closed = new Subject();
    dialog = { open: vi.fn(() => ({ afterClosed: () => closed })) };
    TestBed.configureTestingModule({
      imports: [MenuHost],
      providers: [provideRouter([]), { provide: MatDialog, useValue: dialog }],
    });
    fixture = TestBed.createComponent(MenuHost);
    fixture.componentInstance.item.set(item);
    await fixture.whenStable();
  }

  async function pick(text: string) {
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('#open')!.click();
    await fixture.whenStable();
    const item = await TestbedHarnessEnvironment.documentRootLoader(fixture).getHarness(MatMenuItemHarness.with({ text }));
    await item.click();
    await fixture.whenStable();
  }

  /** The panel the last `open` call showed, and the config it was given. */
  const opened = () => {
    const [component, config] = dialog.open.mock.lastCall!;
    return { component, ...config };
  };

  async function close(result: unknown) {
    closed.next(result);
    closed.complete();
    closed = new Subject();
    await fixture.whenStable();
  }

  describe('for a video', () => {
    it('opens the edit panel on the video', async () => {
      /*
        Given the menu of video "trip.mp4" in "local/movies"
        When the user picks "Edit"
        Then the edit panel opens in full mode on "trip.mp4"
      */
      const trip = aBrowseNode({ name: 'trip.mp4' });
      await showMenuOf(trip);

      await pick('Edit');

      expect(opened()).toMatchObject({ component: VideoEditPanel, data: { mode: 'full', video: trip.node } });
    });

    it('asks to delete just this video', async () => {
      /*
        Given the menu of video "trip" in "local/movies"
        When the user picks "Delete"
        Then the delete panel opens for the single video "trip"
      */
      await showMenuOf(aBrowseNode({ id: 'trip' }));

      await pick('Delete');

      expect(opened()).toMatchObject({
        component: DeleteCheckPanel,
        data: { deleteType: DeleteType.Single, videoIds: new Set(['trip']) },
      });
    });

    it('migrates the video from the directory it sits in and reports the outcome', async () => {
      /*
        Given the menu of video "found.mp4" that a search found in "sub" below "local/movies"
        When the user picks "Migrate"
        Then the migration panel opens on "found.mp4" with its size, from "local/movies/sub"
        When the panel closes having started a migration
        Then a started migration is reported
        When the user migrates again and the panel is dismissed
        Then a migration that did not start is reported
      */
      await showMenuOf(aBrowseNode({ id: 'found', name: 'found.mp4', size: 42, relativePath: 'sub' }));

      await pick('Migrate');
      expect(opened()).toMatchObject({
        component: MigrationPanel,
        data: { videos: [{ id: 'found', name: 'found.mp4', size: 42 }], sourceCurrentDir: 'local/movies/sub' },
      });
      await close(true);

      await pick('Migrate');
      await close(undefined);

      expect(fixture.componentInstance.migrations).toEqual([true, false]);
    });

    it('links to the video page', async () => {
      /*
        Given the menu of video "trip"
        Then "Play Video" links to "/video/trip"
      */
      await showMenuOf(aBrowseNode({ id: 'trip' }));

      (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('#open')!.click();
      await fixture.whenStable();

      expect(document.querySelector('.mat-mdc-menu-panel a')!.getAttribute('href')).toBe('/video/trip');
    });
  });

  describe('for a folder', () => {
    it('syncs the videos of the folder and reports the outcome', async () => {
      /*
        Given the menu of folder "clips" in "local/movies"
        And a toast is showing
        When the user picks "Sync videos"
        Then the toasts are cleared
        And the batch panel opens in directory mode on "local/movies/clips", and cannot be dismissed by clicking outside
        When the panel closes having synced
        Then a sync is reported
      */
      await showMenuOf(aBrowseNode({ name: 'clips', isDir: true }));
      const toasts = TestBed.inject(ToastService);
      toasts.emitNewToast('old news', ToastType.Error);

      await pick('Sync videos');

      expect(toasts.toasts()).toEqual([]);
      expect(opened()).toMatchObject({
        component: BatchOperationPanel,
        data: { mode: 'directory', selectedDirectoryPath: 'local/movies/clips' },
        disableClose: true,
      });
      await close(true);
      expect(fixture.componentInstance.syncs).toEqual([true]);
    });

    it('asks to delete everything in the folder', async () => {
      /*
        Given the menu of folder "clips" in "local/movies"
        When the user picks "Delete all"
        Then the delete panel opens for the directory "local/movies/clips"
      */
      await showMenuOf(aBrowseNode({ name: 'clips', isDir: true }));

      await pick('Delete all');

      expect(opened()).toMatchObject({
        component: DeleteCheckPanel,
        data: { deleteType: DeleteType.Directory, directoryPath: 'local/movies/clips' },
      });
    });

    it('asks to refresh the folder metadata', async () => {
      /*
        Given the menu of folder "clips"
        When the user picks "Refresh Metadata"
        Then a metadata refresh of "clips" is reported
      */
      await showMenuOf(aBrowseNode({ name: 'clips', isDir: true }));

      await pick('Refresh Metadata');

      expect(fixture.componentInstance.refreshed).toEqual(['clips']);
    });
  });
});
