import { Injectable } from "@angular/core";

@Injectable({providedIn: 'root'})
export class PageStateService {

    getState<T>(key: string, crossPage: boolean): T | undefined {
        const item = crossPage ? localStorage.getItem(key) : sessionStorage.getItem(key);
        if(item){
            if (crossPage) {
                localStorage.removeItem(key);
            }else{
                sessionStorage.removeItem(key);
            }
            return JSON.parse(item) as T;
        }
        return undefined;
    }

    setState<T>(key: string, value: T, crossPage: boolean): void {
        if (crossPage) {
            localStorage.setItem(key, JSON.stringify(value));
        } else {
            sessionStorage.setItem(key, JSON.stringify(value));
        }
    }

    clearState(key: string, crossPage: boolean): void {
        if (crossPage) {
            localStorage.removeItem(key);
        } else {
            sessionStorage.removeItem(key);
        }
    }

    /*
      Tab states only: localStorage is shared with other features (the saved theme lives
      there), so it is never cleared wholesale.
    */
    clearAllTabStates(): void {
        sessionStorage.clear();
    }

}