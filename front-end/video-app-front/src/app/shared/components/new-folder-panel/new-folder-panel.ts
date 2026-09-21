import { Component, DestroyRef, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { form, FormField, FormRoot, submit } from '@angular/forms/signals';
import { MatButtonModule } from '@angular/material/button';
import {
  MAT_DIALOG_DATA,
  MatDialogActions,
  MatDialogClose,
  MatDialogContent,
  MatDialogRef,
  MatDialogTitle
} from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { firstValueFrom } from 'rxjs';
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { ToastService } from '../../../services/toast-service/toast.service';
import { folderNameRule } from '../../../services/validation-service/validation.rules';
import { NewFolderPanelData } from '../../models/panels.model';
import { ToastType } from '../../models/toast.model';
import { ToastDisplayer } from '../toast-displayer/toast-displayer';

@Component({
  selector: 'app-new-folder-panel',
  imports: [
    FormField,
    FormRoot,
    MatButtonModule,
    MatDialogActions,
    MatDialogClose,
    MatDialogContent,
    MatDialogTitle,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
    ToastDisplayer
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './new-folder-panel.html',
})
export class NewFolderPanel {
  readonly dialogRef = inject(MatDialogRef<NewFolderPanel>);
  readonly data = inject<NewFolderPanelData>(MAT_DIALOG_DATA);
  private gqlService = inject(GqlService);
  private toastService = inject(ToastService);
  private destroyRef = inject(DestroyRef);

  private model = signal({ name: '' });

  /*
    Submission lives in the form options rather than in a click handler so that `formRoot`
    can drive it too — that is what keeps Enter submitting the dialog.
  */
  folderForm = form(
    this.model,
    path => folderNameRule(path.name),
    { submission: { action: () => this.createDirectory() } },
  );

  submitForm() {
    if (this.folderForm().submitting()) return;
    submit(this.folderForm);
  }

  private async createDirectory(): Promise<null> {
    const name = this.model().name.trim();

    try {
      const result = await firstValueFrom(
        this.gqlService
          .createDirectoryMutation(this.data.parentPath || undefined, name)
          .pipe(takeUntilDestroyed(this.destroyRef)),
        { defaultValue: null },
      );

      // The dialog was destroyed before the mutation answered; nothing left to report to.
      if (result === null) return null;

      if (result.error) {
        // GqlService has already raised the toast. The dialog stays open: a name
        // clash is the likeliest rejection, and retyping is the whole fix.
        return null;
      }
      if (result.data?.success) {
        this.toastService.emitNewToast(
          `Folder "${result.data.name}" created.`, ToastType.Success
        );
        this.dialogRef.close(true);
      } else {
        this.toastService.emitNewToast('Failed to create the folder.', ToastType.Error);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      this.toastService.emitNewToast(`Failed to create the folder: ${message}`, ToastType.Error);
    }

    return null;
  }
}
