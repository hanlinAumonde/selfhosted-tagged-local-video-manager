import { Routes } from '@angular/router';
import { VideoMetaDataResolver } from './route-resolver/video-player.resolver';

export const routes: Routes = [
  {
    path: '',
    redirectTo: '/home',
    pathMatch: 'full',
  },
  {
    path: 'home',
    title: 'Home Page - Tagged Local Video App',
    loadComponent: () => import('./pages/homepage/homepage').then(m => m.Homepage),
    data: { headerTitle: 'HomePage' }
  },
  {
    path: 'search',
    title: 'Search videos - Tagged Local Video App',
    loadComponent: () => import('./pages/search/search').then(m => m.Search),
    data: { headerTitle: 'Search' }
  },
  {
    path: 'video/:id',
    loadComponent: () => import('./pages/video-player/video-player').then(m => m.VideoPlayer),
    title: 'Video Player - Tagged Local Video App',
    runGuardsAndResolvers: 'paramsChange',
    resolve: {
      video: VideoMetaDataResolver
    }
  },
  {
    path: 'file-browser',
    loadComponent: () => import('./pages/file-browser/file-browser').then(m => m.FileBrowser),
    title: 'File Browser - Tagged Local Video App',
    data: { headerTitle: 'File Browser' }
  },
  {
    path: 'management',
    loadComponent: () => import('./pages/management/management').then(m => m.Management),
    title: 'Management - Tagged Local Video App',
    data: { headerTitle: 'Management' }
  },
  {
    path: '**',
    redirectTo: '/home',
  },
];
