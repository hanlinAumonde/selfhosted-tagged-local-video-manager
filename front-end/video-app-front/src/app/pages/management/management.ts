import { Component, signal, ChangeDetectionStrategy } from '@angular/core';
import { MatTabsModule } from '@angular/material/tabs';
import { MatIconModule } from '@angular/material/icon';
import { MigrationTaskList } from '../../shared/components/migration-task-list/migration-task-list';

interface TaskCategory {
  label: string;
  icon: string;
}

@Component({
  selector: 'app-management',
  imports: [
    MatTabsModule,
    MatIconModule,
    MigrationTaskList,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './management.html'
})
export class Management {
  activeTab = signal<number>(0);
  activeTaskCategory = signal<number>(0);

  taskCategories: TaskCategory[] = [
    { label: 'Migration', icon: 'drive_file_move' },
  ];

  onTabChange(index: number) {
    this.activeTab.set(index);
  }

  selectTaskCategory(index: number) {
    this.activeTaskCategory.set(index);
  }
}
