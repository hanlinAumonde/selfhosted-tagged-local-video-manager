import {
  Component,
  inject,
  signal,
  computed,
  effect,
  DestroyRef,
  ChangeDetectionStrategy
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { take } from 'rxjs/operators';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { GqlService } from '../../services/GQL-service/GQL.service';
import { VideoEditPanel } from '../../shared/components/video-edit-panel/video-edit-panel';
import { SeriesPanel } from '../../shared/components/series-panel/series-panel';
import { VideoPlayerHost } from '../../shared/components/video-player-host/video-player-host';
import { VideoEditPanelData } from '../../shared/models/panels.model';
import { 
  ResultState, 
  VideoDetail, 
  VideoMutationDetail, 
  VideoRecordViewDetail 
} from '../../shared/models/GQL-result.model';
import { environment } from '../../../environments/environment';
import { SearchPageParam } from '../../shared/models/search.model';
import { Title } from '@angular/platform-browser';
import { ToastService } from '../../services/toast-service/toast.service';
import { PageStateService } from '../../services/Page-state-service/page-state.service';
import { VideoUpdateEventService } from '../../services/video-update-event-service/video-update-event.service';
import { VideoUpdateType } from '../../shared/models/events.model';
import { switchMap, EMPTY } from 'rxjs';
import { ToastType } from '../../shared/models/toast.model';

@Component({
  selector: 'app-video-player',
  imports: [
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    RouterLink,
    SeriesPanel,
    VideoPlayerHost,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  templateUrl: './video-player.html'
})
export class VideoPlayer {
  private route = inject(ActivatedRoute);
  private gqlService = inject(GqlService);
  private stateService = inject(PageStateService);
  private dialog = inject(MatDialog);
  private title = inject(Title);
  private toastService = inject(ToastService);
  private videoUpdateEventService = inject(VideoUpdateEventService);
  private router = inject(Router);
  private destroyRef = inject(DestroyRef);
  private hasRecordedView = signal<boolean>(false);
  private videoDataLoaded = toSignal(this.route.data)

  searchPageApi = environment.searchpage_api;

  video = signal<ResultState<VideoDetail | null>>(this.gqlService.initialSignalData<VideoDetail | null>(null));
  
  videoId = computed(() => this.video().data?.id ?? null);

  videoStreamUrl = computed(() => {
    const id = this.videoId();
    return id ? environment.backend_api + environment.video_stream_api + id : '';
  });

  formattedViews = computed(() => {
    const count = this.video()?.data?.viewCount ?? 0;
    if (count < 1000) return count.toString();
    if (count < 1_000_000) return (count / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
    return (count / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
  });

  constructor() {
    effect(() => {
      this.video.set(this.videoDataLoaded()!['video']);
      this.hasRecordedView.set(false);
    });

    effect(() => {
      const videoData = this.video().data;
      if (videoData) {
        this.title.setTitle(`${videoData.name} - Tagged Local Video App`);
      }
    })

    this.videoUpdateEventService.onEvent().pipe(
      takeUntilDestroyed(),
      switchMap(event => {
        const currentId = this.videoId();
        if (!currentId || !event.videoIds.includes(currentId)) return EMPTY;

        if (event.type === VideoUpdateType.Deleted) {
          this.toastService.emitNewToast(
            'The video you are watching has been deleted.', 
            ToastType.Warning
          );
          this.router.navigate(['/']);
          return EMPTY;
        }

        // Re-fetch video data for updates
        return this.gqlService.getVideoByIdQuery(currentId);
      })
    ).subscribe(result => {
      if (!result.loading && result.data) {
        this.video.set(result);
      }
    });
  }

  recordView() {
    const id = this.videoId();
    if (this.hasRecordedView() || !id) return;

    this.hasRecordedView.set(true);
    this.gqlService.recordVideoViewMutation(id)
      .pipe(take(1), takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          if (!result.data?.success) {
            this.toastService.emitNewToast('Failed to record video view', ToastType.Error);
          }else if(result.data.video){
            this.video.update(current => {
              if (!current.data) return current;
              return this.toVideoDetailResultState(result.data!, current);
            });
          }
        }
      });
  }

  onLovedClick() {
    const videoData = this.video().data;
    if (!videoData) return;

    this.gqlService.updateVideoMetadataMutation(
      videoData.id,
      !videoData.loved,
      videoData.tags.map(tag => tag.name),
    )
    .pipe(take(1), takeUntilDestroyed(this.destroyRef))
    .subscribe({
      next: (result) => {
        if (result.data?.success && result.data.video) {
          this.videoUpdateEventService.emitUpdated([videoData.id]);
          this.video.update(current => {
            if (!current.data) return current;
            return this.toVideoDetailResultState(result.data!, current);
          })
        }else{
          this.toastService.emitNewToast('Failed to update loved status', ToastType.Error);
        }
      }
    });
  }

  onEditClick() {
    const videoData = this.video().data;
    if (!videoData) return;

    const dialogData: VideoEditPanelData = {
      mode: 'full',
      video: videoData as VideoDetail,
    };

    const dialogRef = this.dialog.open(VideoEditPanel, {
      width: '600px',
      maxHeight: '90vh',
      data: dialogData,
    });

    dialogRef.afterClosed().subscribe(
      (result: VideoMutationDetail) => {
        if (result && result.video) {
          this.video.update(current => {
            return this.toVideoDetailResultState(result, current);
          });
        }
      }
    )
  }

  searchPageState(state: string, option: "author" | "tags"): SearchPageParam {
    return option === "author" ? { author: state } : { tags: [state] };
  }

  onTagClick(tagName: string) {
    this.stateService.setState<SearchPageParam>(
      environment.searchpage_api, 
      this.searchPageState(tagName, "tags"), 
      true
    );
  }

  onAuthorClick(author: string) {
    this.stateService.setState<SearchPageParam>(
      environment.searchpage_api, 
      this.searchPageState(author, "author"), 
      true
    );
  }

  toVideoDetailResultState(updatedData: VideoMutationDetail | VideoRecordViewDetail, 
                           currentData: ResultState<VideoDetail | null>
                          ): ResultState<VideoDetail | null> {
    if('viewCount' in updatedData.video!){
      return {
        ...currentData,
        data: {
          ...currentData.data!,
          viewCount: updatedData.video!.viewCount!,
          lastViewTime: updatedData.video!.lastViewTime!,
        }
      }
    }else{
      return {
        ...currentData,
        data: {
          ...currentData.data!,
          loved: updatedData.video!.loved!,
          name: updatedData.video!.name!,
          introduction: updatedData.video!.introduction!,
          author: updatedData.video!.author!,
          tags: updatedData.video!.tags!,
          // The mutation returns these too; dropping them left the Series chip
          // showing the old name/order until an unrelated refetch happened to land.
          seriesName: updatedData.video!.seriesName,
          seriesOrder: updatedData.video!.seriesOrder,
        }
      }
    }
  }
}