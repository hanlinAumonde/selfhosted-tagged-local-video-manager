import { Component, inject, input, output, viewChild, ChangeDetectionStrategy } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatMenu, MatMenuModule } from '@angular/material/menu';
import { MatDialog } from '@angular/material/dialog';
import { RouterLink } from '@angular/router';
import { BrowsedVideo, FileBrowseNode } from '../../models/GQL-result.model';
import { environment } from '../../../../environments/environment';
import { ToastService } from '../../../services/toast-service/toast.service';
import { BatchOperationPanel } from '../batch-operation-panel/batch-operation-panel';
import { DeleteCheckPanel } from '../delete-check-panel/delete-check-panel';
import { VideoEditPanel } from '../video-edit-panel/video-edit-panel';
import { MigrationPanel } from '../migration-panel/migration-panel';
import {
  DeleteCheckPanelData,
  DeleteType,
  MigrationPanelData,
  VideoEditPanelData,
  VideoEditPanelMode
} from '../../models/panels.model';
import { isNodeLocked, nodeDirectory } from '../../models/management.model';

/**
 * The operations menu of one file browser entry. Both the table and the thumbnail grid
 * attach this same menu, so the two views cannot drift apart in what they offer.
 *
 * Usage: `<app-file-node-menu #m [item]="item" ... />` then `[matContextMenuTriggerFor]="m.menu()!"`.
 */
@Component({
  selector: 'app-file-node-menu',
  imports: [MatIconModule, MatMenuModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'hidden' },
  templateUrl: './file-node-menu.html'
})
export class FileNodeMenu {
  item = input.required<FileBrowseNode>();
  currentPath = input.required<string[]>();

  refreshDirectoryMeta = output<FileBrowseNode>();
  migrationResult = output<boolean>();
  batchSyncDirectoryResult = output<boolean>();

  menu = viewChild(MatMenu);

  private toastService = inject(ToastService);
  private dialog = inject(MatDialog);

  isLocked(node: BrowsedVideo): boolean {
    return isNodeLocked(node);
  }

  videoPage(video: BrowsedVideo) {
    return [environment.videopage_api, video.id];
  }

  openEditPanel(video: BrowsedVideo) {
    this.dialog.open(VideoEditPanel, {
      width: '500px',
      data: {
        mode: 'full' as VideoEditPanelMode,
        video: video
      } as VideoEditPanelData
    });
  }

  deleteVideo(video: BrowsedVideo) {
    this.dialog.open(DeleteCheckPanel, {
      width: '400px',
      data: {
        deleteType: DeleteType.Single,
        videoIds: new Set<string>([video.id])
       } as DeleteCheckPanelData
    });
  }

  deleteVideosInDirectory(dirPath: string) {
    this.dialog.open(DeleteCheckPanel, {
      width: '400px',
      data: {
        deleteType: DeleteType.Directory,
        directoryPath: this.currentPath().join('/') + '/' + dirPath
       } as DeleteCheckPanelData
    });
  }

  openMigrationPanel(video: BrowsedVideo) {
    const data: MigrationPanelData = {
      sourceVideoId: video.id,
      sourceVideoName: video.name,
      sourceFileSize: video.size,
      sourceCurrentDir: nodeDirectory(this.currentPath(), video) || '/',
    };

    const dialogRef = this.dialog.open(MigrationPanel, {
      width: '560px',
      data,
    });

    dialogRef.afterClosed().subscribe(result => {
      this.migrationResult.emit(!!result);
    });
  }

  openBatchOperationPanel(dirName: string) {
    if (!dirName) return;

    const selectedDirectoryPath = this.currentPath().length > 0 ?
      this.currentPath().join('/') + '/' + dirName : dirName;

    const data = { mode: 'directory', selectedDirectoryPath: selectedDirectoryPath };

    this.toastService.clearAllToasts();

    const dialogRef = this.dialog.open(BatchOperationPanel, {
      width: '500px',
      data: data,
      disableClose: true,
    });

    dialogRef.afterClosed().subscribe(result => {
      this.batchSyncDirectoryResult.emit(result ? true : false);
    });
  }
}
