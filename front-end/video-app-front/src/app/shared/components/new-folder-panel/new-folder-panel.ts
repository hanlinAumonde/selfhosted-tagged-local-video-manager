import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, ReactiveFormsModule } from '@angular/forms';
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
import { GqlService } from '../../../services/GQL-service/GQL.service';
import { ToastService } from '../../../services/toast-service/toast.service';
import { ValidationService } from '../../../services/validation-service/validation.service';
import { NewFolderPanelData } from '../../models/panels.model';
import { ToastType } from '../../models/toast.model';
import { ToastDisplayer } from '../toast-displayer/toast-displayer';

@Component({
  selector: 'app-new-folder-panel',
  imports: [
    ReactiveFormsModule,
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
  templateUrl: './new-folder-panel.html',
})
export class NewFolderPanel {
  readonly dialogRef = inject(MatDialogRef<NewFolderPanel>);
  readonly data = inject<NewFolderPanelData>(MAT_DIALOG_DATA);
  private fb = inject(FormBuilder);
  private gqlService = inject(GqlService);
  private toastService = inject(ToastService);
  private validationService = inject(ValidationService);
  private destroyRef = inject(DestroyRef);

  isSaving = signal<boolean>(false);

  folderForm = this.fb.group({
    name: ['', [this.validationService.folderNameValidator()]]
  });

  get name() { return this.folderForm.get('name') as FormControl<string>; }

  errorMessage(): string {
    const errors = this.name.errors;
    if (!errors) return '';
    if (errors['required']) return 'A folder name is required';
    if (errors['folderSeparator']) return 'A folder name cannot contain "/" or "\\"';
    if (errors['folderRelativeReference']) return 'That is not a folder name';
    if (errors['maxLength']) return `Maximum length is ${errors['maxLength'].max} characters`;
    return 'Invalid folder name';
  }

  createFolder() {
    if (this.folderForm.invalid || this.isSaving()) return;

    const name = (this.folderForm.value.name ?? '').trim();
    this.isSaving.set(true);

    this.gqlService.createDirectoryMutation(this.data.parentPath || undefined, name)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: result => {
          this.isSaving.set(false);
          if (result.error) {
            // GqlService has already raised the toast. The dialog stays open: a name
            // clash is the likeliest rejection, and retyping is the whole fix.
            return;
          }
          if (result.data?.success) {
            this.toastService.emitNewToast(
              `Folder "${result.data.name}" created.`, ToastType.Success
            );
            this.dialogRef.close(true);
          } else {
            this.toastService.emitNewToast('Failed to create the folder.', ToastType.Error);
          }
        },
        error: err => {
          this.isSaving.set(false);
          this.toastService.emitNewToast(
            `Failed to create the folder: ${err.message || err}`, ToastType.Error
          );
        }
      });
  }
}
