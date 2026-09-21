import {
  Component,
  computed,
  input,
  output,
  ChangeDetectionStrategy
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-pagination',
  standalone: true,
  imports: [MatButtonModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './pagination.html',
})
export class Pagination {

  readonly isActive = input<boolean>(true);

  currentPage = input<number>(1);
  totalPages = input<number>(0);

  pageChanged = output<number>();

  isFirstPage = computed(() => this.currentPage() === 1);
  isLastPage = computed(() => this.currentPage() === this.totalPages());

  // Always show a fixed number of page buttons centered around the current page
  pages = computed(() => {
    const total = this.totalPages();
    const current = this.currentPage();

    if(total <= environment.pageListSize){ 
      return Array.from({ length: total }, (_, i) => i + 1);
    }

    const pages: number[] = [];
    const halfSize = Math.floor(environment.pageListSize / 2);
    
    let startPage = Math.max(1, current - halfSize);
    let endPage = Math.min(total, current + halfSize);
    
    if (endPage - startPage + 1 < environment.pageListSize) {
      if(startPage === 1){
        endPage = Math.min(total, startPage + environment.pageListSize - 1);
      }
      else if(endPage === total){
        startPage = Math.max(1, endPage - environment.pageListSize + 1);
      }
    }
    for (let i = startPage; i <= endPage; i++) {
      pages.push(i);
    }
    return pages;
  });

  changePage(page: number): void {
    if (page < 1 || page > this.totalPages()) return;
    this.pageChanged.emit(page);
  }

  switchToEdgePage(isFirst: boolean){
    const targetPage = isFirst? 1 : this.totalPages();
    this.changePage(targetPage);
  }
}
