import { Component, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { PageStateService } from '../../../services/Page-state-service/page-state.service';
import { environment } from '../../../../environments/environment.development';

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

@Component({
  selector: 'app-sidebar',
  imports: [RouterLink, RouterLinkActive, MatIconModule, MatButtonModule, MatTooltipModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './sidebar.html'
})
export class Sidebar {
  private stateService = inject(PageStateService);

  isExpanded = signal(false);

  navItems: NavItem[] = [
    {
      path: '/home',
      label: 'HomePage',
      icon: 'home',
    },
    {
      path: '/search',
      label: 'Search',
      icon: 'search',
    },
    {
      path: '/file-browser',
      label: 'File Browser',
      icon: 'folder',
    },
    {
      path: '/management',
      label: 'Management',
      icon: 'settings',
    },
  ];

  onNavItemClick() {
    this.stateService.clearAllStates(false);
  }
  
  scrollTo(position: number) {
    const mainContainer = document.getElementById(environment.containerIds.rootMainContainerId);
    if (mainContainer) {
      mainContainer.scrollTo({ top: position, behavior: 'smooth' });
    }
  }
}
