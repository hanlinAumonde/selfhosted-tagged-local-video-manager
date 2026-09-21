import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { ActivatedRoute, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { Sidebar } from './shared/components/sidebar/sidebar';
import { Header } from './shared/components/header/header';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map } from 'rxjs';
import { environment } from '../environments/environment';
import { ToastDisplayer } from "./shared/components/toast-displayer/toast-displayer";
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, Sidebar, Header, ToastDisplayer, MatIconModule],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './app.html'
})
export class App {
  private router = inject(Router);
  private activatedRoute = inject(ActivatedRoute);

  rootMainContainerId = environment.containerIds.rootMainContainerId;

  headerTitle = toSignal(
    this.router.events.pipe(
      filter(event => event instanceof NavigationEnd),
      map(() => {
        let route = this.activatedRoute;
        while (route.firstChild) {
          route = route.firstChild;
        }
        if(route.snapshot.data['video']){
          return "Video Player";
        }
        return route.snapshot.data['headerTitle'] ?? 'Loading...';
      })
    ),
    { initialValue: 'Loading...' }
  );
}