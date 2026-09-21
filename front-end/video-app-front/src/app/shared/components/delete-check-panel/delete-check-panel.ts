import { Component, computed, inject, OnDestroy, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { 
  MAT_DIALOG_DATA, 
  MatDialogActions, 
  MatDialogClose, 
  MatDialogContent, 
  MatDialogRef, 
  MatDialogTitle 
} from '@angular/material/dialog';
import { DeleteCheckPanelData, DeleteType } from '../../models/panels.model';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { Observable, tap } from 'rxjs';
import { ToastService } from '../../../services/toast-service/toast.service';
import { BatchResultType, DirectoryDeletionStrategy } from '../../../core/graphql/generated/graphql';
import { ToastDisplayer } from "../toast-displayer/toast-displayer";
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatRadioModule } from '@angular/material/radio';
import { VideoUpdateEventService } from '../../../services/video-update-event-service/video-update-event.service';
import { ToastType } from '../../models/toast.model';

@Component({
  selector: 'app-delete-check-panel',
  imports: [
    MatButtonModule, 
    MatDialogActions, 
    MatDialogClose, 
    MatDialogTitle, 
    MatDialogContent, 
    MatProgressBarModule,
    MatRadioModule,
    ToastDisplayer
  ],
  templateUrl: './delete-check-panel.html',
})
export class DeleteCheckPanel implements OnDestroy {
  readonly dialogRef = inject(MatDialogRef<DeleteCheckPanel>);
  readonly data = inject<DeleteCheckPanelData>(MAT_DIALOG_DATA);
  private gqlService = inject(GqlService);
  private toastService = inject(ToastService);
  private videoUpdateEventService = inject(VideoUpdateEventService);
  private gqlRequest$!: Observable<any>;

  processingMessage = signal<string>("");
  isSaving = signal<boolean>(false);

  ngOnDestroy(): void {
    if(this.gqlRequest$) {
      this.gqlRequest$.subscribe().unsubscribe();
    }
  }

  readonly isDirectoryDelete = this.data.deleteType === DeleteType.Directory;
  readonly KeepFolder = DirectoryDeletionStrategy.KeepFolder;
  readonly DeleteFolder = DirectoryDeletionStrategy.DeleteFolder;

  folderDisposition = signal<DirectoryDeletionStrategy>(DirectoryDeletionStrategy.KeepFolder);

  textToDelete = computed(() => {
    switch(this.data.deleteType){
      case DeleteType.Single:
        return "this video";
      case DeleteType.Batch:
        return `the selected ${this.data.videoCount} videos`;
      case DeleteType.Directory:
        return `everything in the directory "${this.data.directoryPath}"`;
      default:
        return "the selected items";
    }
  });

  confirmDelete() {
    this.isSaving.set(true);
    const type = this.data.deleteType;
    if(!this.data.videoIds && !this.data.directoryPath) {
      this.isSaving.set(false);
      this.toastService.emitNewToast(
        'No videoIds or directoryPath provided for deletion.', ToastType.Error
      );
      this.dialogRef.close(false);
      return;
    }
    switch(type){
      case DeleteType.Single:
        this.gqlRequest$ = this.processDeletionMutation();
        break;
      case DeleteType.Batch:
        this.gqlRequest$ = this.processBatchDeletion(
          this.gqlService.batchDeleteVideosSubscription(
          { 
            videoIds: this.data.videoIds ? Array.from(this.data.videoIds) : [],
            relativePath: { relativePath: this.data.directoryPath ? this.data.directoryPath : "" }
          })
        );
        break;
      case DeleteType.Directory:
        this.gqlRequest$ = this.processBatchDeletion(
          this.gqlService.batchDeleteVideosSubscription(
          {
            videoIds: [],
            relativePath: { relativePath: this.data.directoryPath ? this.data.directoryPath : "" },
            directoryDeletion: this.folderDisposition()
          })
        );
        break;
    }
    if(!this.gqlRequest$) {
      this.toastService.emitNewToast(
        'No deletion operation specified.', ToastType.Error
      );
      this.dialogRef.close(false);
      return;
    }
    this.gqlRequest$.subscribe({
      error: (err) => {
        this.isSaving.set(false);
        this.toastService.emitNewToast(
          `An error occurred during deletion: ${err.message || err}`, ToastType.Error
        );
        this.dialogRef.close(false);
      }
    })
  }

  processDeletionMutation(){
    const gqlRequest$ = this.gqlService.deleteVideoMutation(
      this.data.videoIds ? Array.from(this.data.videoIds)[0] : ""
    );
    return gqlRequest$.pipe(
      tap(result => {
        this.isSaving.set(false);
        if(result.data?.success){
          this.videoUpdateEventService.emitVideosDeleted(
            this.data.videoIds ? Array.from(this.data.videoIds) : []
          );
          this.toastService.emitNewToast('Video deleted successfully.', ToastType.Success);
          this.dialogRef.close(true);
        }else{
          this.toastService.emitNewToast('Failed to delete video.', ToastType.Error);
          this.dialogRef.close(false);
        }
      })
    )
  }

  processBatchDeletion(gqlRequest$: Observable<any>) {
    return gqlRequest$.pipe(
      tap(
        result => {
          if(result.data?.result?.resultType === undefined && result.data?.status){
            this.processingMessage.set(result.data.status);
          }else if(result.data?.result?.resultType){
            this.isSaving.set(false);
            const resultType = result.data.result.resultType;
            switch(resultType) {
              case BatchResultType.Success:
              case BatchResultType.PartialSuccess:
                if(this.data.videoIds && this.data.videoIds.size > 0) {
                  this.videoUpdateEventService.emitVideosDeleted(Array.from(this.data.videoIds));
                } else if(this.data.directoryPath) {
                  this.videoUpdateEventService.emitDirectoryDeleted(this.data.directoryPath);
                }
                if(resultType === BatchResultType.PartialSuccess) {
                  this.toastService.emitNewToast(
                    `Batch delete completed with partial success, some videos may not have been deleted.
                    \nMessage: ${result.data.result.message ?? 'No additional information provided.'}`,
                    ToastType.Warning
                  );
                } else {
                  this.toastService.emitNewToast('Batch delete completed successfully.', ToastType.Success);
                }
                this.dialogRef.close(true);
                break;
              case BatchResultType.Failure:
                this.toastService.emitNewToast(
                  `Batch delete failed. Please try again.
                  \nMessage: ${result.data.result.message ?? 'No additional information provided.'}`, 
                  ToastType.Error
                );
                this.dialogRef.close(false);
                break;
            }
          }
        }
      )
    );
  }
}
