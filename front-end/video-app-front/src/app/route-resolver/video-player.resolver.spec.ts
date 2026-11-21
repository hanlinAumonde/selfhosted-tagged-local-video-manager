import { Component, inject } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { toSignal } from '@angular/core/rxjs-interop';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';
import { MockInstance } from 'vitest';

import { VideoMetaDataResolver } from './video-player.resolver';
import { GetVideoByIdDocument } from '../core/graphql/generated/graphql';
import { ToastService } from '../services/toast-service/toast.service';
import { ToastType } from '../shared/models/toast.model';
import { apolloAsInTheApp } from '../../testing/apollo-testing';
import { aVideoDetail } from '../../testing/video-fixtures';

const tick = () => new Promise<void>(resolve => setTimeout(resolve));

@Component({ selector: 'video-page', template: 'video page' })
class VideoPage {
  resolved = toSignal(inject(ActivatedRoute).data);
}

@Component({ selector: 'home-page', template: 'home page' })
class HomePage {}

describe('VideoMetaDataResolver', () => {
  let harness: RouterTestingHarness;
  let apollo: ApolloTestingController;
  let toast: MockInstance<ToastService['emitNewToast']>;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      imports: [ApolloTestingModule],
      providers: [
        provideRouter([
          { path: 'video/:id', component: VideoPage, resolve: { video: VideoMetaDataResolver } },
          { path: 'home', component: HomePage },
        ]),
      ],
    });
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
    harness = await RouterTestingHarness.create();
  });

  /** Opens `url`, letting the resolver's query be answered with `answer` on the way. */
  async function open(url: string, answer: (op: ReturnType<ApolloTestingController['expectOne']>) => void) {
    const navigation = harness.navigateByUrl(url);
    await tick();
    answer(apollo.expectOne(GetVideoByIdDocument));
    await navigation;
    return TestBed.inject(Router).url;
  }

  it('opens the video page with the video already loaded', async () => {
    /*
      Given video "v1" exists and no migration holds it
      When the user opens "/video/v1"
      Then the video page opens with "v1" resolved
    */
    const v1 = aVideoDetail({ id: 'v1' });

    expect(await open('/video/v1', op => op.flushData({ getVideoById: v1 }))).toBe('/video/v1');

    const page = harness.routeDebugElement!.componentInstance as VideoPage;
    expect(page.resolved()!['video']).toMatchObject({ loading: false, error: null, data: { id: 'v1' } });
    expect(toast).not.toHaveBeenCalled();
  });

  it('sends the user home when the video cannot be loaded', async () => {
    /*
      Given loading video "v1" fails
      When the user opens "/video/v1"
      Then the user lands on the home page and an error toast explains why
    */
    expect(await open('/video/v1', op => op.networkError(new Error('down')))).toBe('/home');

    expect(toast).toHaveBeenCalledWith(expect.stringContaining('Failed to resolve video metadata'), ToastType.Error);
  });

  it('sends the user home while a migration holds the video', async () => {
    /*
      Given video "busy" is held by a migration
      When the user opens "/video/busy"
      Then the user lands on the home page and a warning toast says it is being migrated
    */
    const busy = aVideoDetail({ id: 'busy', isLocked: true });

    expect(await open('/video/busy', op => op.flushData({ getVideoById: busy }))).toBe('/home');

    expect(toast).toHaveBeenCalledWith(expect.stringContaining('being migrated'), ToastType.Warning);
  });
});
