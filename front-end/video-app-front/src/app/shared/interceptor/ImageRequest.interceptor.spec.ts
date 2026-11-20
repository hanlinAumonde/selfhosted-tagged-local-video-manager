import { TestBed } from '@angular/core/testing';
import { HTTP_INTERCEPTORS, HttpClient, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { firstValueFrom } from 'rxjs';
import { MockInstance } from 'vitest';

import { ImageRequestInterceptor } from './ImageRequest.interceptor';
import { ToastService } from '../../services/toast-service/toast.service';
import { ToastType } from '../models/toast.model';

describe('ImageRequestInterceptor', () => {
  let http: HttpClient;
  let backend: HttpTestingController;
  let toast: MockInstance<ToastService['emitNewToast']>;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        { provide: HTTP_INTERCEPTORS, useClass: ImageRequestInterceptor, multi: true },
      ],
    });
    http = TestBed.inject(HttpClient);
    backend = TestBed.inject(HttpTestingController);
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
  });

  afterEach(() => backend.verify());

  async function failingRequest(url: string, params: Record<string, string> = {}) {
    const response = firstValueFrom(http.get(url, { params }));
    backend.expectOne(() => true).flush('nope', { status: 500, statusText: 'Server Error' });
    return response.then(() => 'succeeded', () => 'failed');
  }

  it('tells the user which video a thumbnail failed to load for', async () => {
    /*
      Given the thumbnail request for video "v1" fails
      Then an error toast names "v1"
      And the caller still sees the failure
    */
    expect(await failingRequest('/video/thumbnail', { video_id: 'v1' })).toBe('failed');

    expect(toast).toHaveBeenCalledWith(expect.stringContaining('video_id: v1'), ToastType.Error);
  });

  it('stays quiet about any other failing request', async () => {
    /*
      Given a request that is not for a thumbnail fails
      Then no toast is shown
      And the caller still sees the failure
    */
    expect(await failingRequest('/graphql')).toBe('failed');

    expect(toast).not.toHaveBeenCalled();
  });
});
