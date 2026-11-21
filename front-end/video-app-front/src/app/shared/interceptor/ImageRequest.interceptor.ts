import { HttpHandler, HttpInterceptor, HttpRequest } from "@angular/common/http";
import { inject, Injectable } from "@angular/core";
import { environment } from "../../../environments/environment";
import { catchError } from "rxjs";
import { ToastService } from "../../services/toast-service/toast.service";
import { ToastType } from "../models/toast.model";

@Injectable({
  providedIn: "root",
})
export class ImageRequestInterceptor implements HttpInterceptor {
    private toastService = inject(ToastService);

    intercept(req: HttpRequest<any>, next: HttpHandler) {
        return next.handle(req).pipe(
            catchError((error) => {
                // Streams never pass through here: the <video> element loads them itself.
                if(req.url.includes(environment.videopage_thumbnail_api)) {
                    this.toastService.emitNewToast(
                        `Failed to load video thumbnail image or video duration - video_id: ${req.params.get('video_id')}`,
                        ToastType.Error
                    );
                }
                throw error;
            })
        );
    }
}