import { Component, inject, input, ChangeDetectionStrategy } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ThemeService } from '../../../services/theme-service/theme.service';

@Component({
  selector: 'app-header',
  imports: [MatIconModule, MatButtonModule, MatTooltipModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './header.html'
})
export class Header {
  themeService = inject(ThemeService);
  title = input<string>('Dashboard');
}
