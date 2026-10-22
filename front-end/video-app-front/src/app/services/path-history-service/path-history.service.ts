import { Injectable } from "@angular/core";

@Injectable({
    providedIn: "root",
})
export class PathHistoryService {
    private pathStack1: string[][] = [];
    private pathStack2: string[][] = [];
    /*
      Keyed by path rather than by history entry: a breadcrumb jump to an ancestor is not a
      back step, yet it should land where that directory was left, just like one.
    */
    private scrollByPath = new Map<string, number>();

    rememberScroll(path: string[], scrollTop: number): void {
        this.scrollByPath.set(path.join('/'), scrollTop);
    }

    /** The top for a directory never left in this visit. */
    scrollOf(path: string[]): number {
        return this.scrollByPath.get(path.join('/')) ?? 0;
    }

    pushNewPath(path: string[]): void {
        this.pathStack2 = [];
        this.pathStack1.push([...path]);
    }

    pushForwardPath(): string[] | undefined {
        const path = this.pathStack2.pop();
        if (path !== undefined) {
            this.pathStack1.push(path);
        }
        return this.getCurrentPath();
    }

    popHisotryPath(): string[] | undefined {
        const path = this.pathStack1.pop();
        if (path !== undefined) {
            this.pathStack2.push(path);
        }
        return this.getCurrentPath();
    }

    hasHistory(): boolean {
        return this.pathStack1.length > 0;
    }

    hasForward(): boolean {
        return this.pathStack2.length > 0;
    }

    clearAllHistory(): void {
        this.pathStack1 = [];
        this.pathStack2 = [];
        this.scrollByPath.clear();
    }

    private getCurrentPath(): string[] | undefined {
        const current = this.pathStack1[this.pathStack1.length - 1];
        return current ? [...current] : undefined;
    }
}
