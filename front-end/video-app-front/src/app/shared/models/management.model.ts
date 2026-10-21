import { BrowsedVideo, FileBrowseNode } from "./GQL-result.model";

export type FileBrowserViewMode = 'table' | 'grid';

export type SortCriterion = {
    index: number;
    order: boolean; // true for ascending, false for descending
}

export type ManagementRefreshState = {
  currentPath?: string[];
  scrollPosition: number;
  sortCriteria: SortCriterion;
};

export enum ItemsSortOption {
  NAME_ASC = 'NAME_ASC',
  NAME_DESC = 'NAME_DESC',
  SIZE_ASC = 'SIZE_ASC',
  SIZE_DESC = 'SIZE_DESC',
  DATE_ASC = 'DATE_ASC',
  DATE_DESC = 'DATE_DESC'
}

const SortOptionMapping: { [key: number]: { asc: ItemsSortOption, desc: ItemsSortOption } } = {
  0: { asc: ItemsSortOption.NAME_ASC, desc: ItemsSortOption.NAME_DESC },
  1: { asc: ItemsSortOption.SIZE_ASC, desc: ItemsSortOption.SIZE_DESC },
  2: { asc: ItemsSortOption.DATE_ASC, desc: ItemsSortOption.DATE_DESC }
};

export function comparatorBySortOption(sortCriterion: SortCriterion): (a: FileBrowseNode, b: FileBrowseNode) => number {
    const mapping = SortOptionMapping[sortCriterion.index];
    const option = sortCriterion.order ? mapping.asc : mapping.desc;
    switch(option){
        case ItemsSortOption.NAME_ASC:
            return (a: FileBrowseNode, b: FileBrowseNode) => a.node.name.localeCompare(b.node.name);
        case ItemsSortOption.NAME_DESC:
            return (a: FileBrowseNode, b: FileBrowseNode) => b.node.name.localeCompare(a.node.name);
        case ItemsSortOption.SIZE_ASC:
            return (a: FileBrowseNode, b: FileBrowseNode) => (a.node.size ?? 0) - (b.node.size ?? 0);
        case ItemsSortOption.SIZE_DESC:
            return (a: FileBrowseNode, b: FileBrowseNode) => (b.node.size ?? 0) - (a.node.size ?? 0);
        case ItemsSortOption.DATE_ASC:
            return (a: FileBrowseNode, b: FileBrowseNode) => (a.node.lastModifyTime ?? 0) - (b.node.lastModifyTime ?? 0);
        case ItemsSortOption.DATE_DESC:
            return (a: FileBrowseNode, b: FileBrowseNode) => (b.node.lastModifyTime ?? 0) - (a.node.lastModifyTime ?? 0);
    }
}

/**
 * Whether a migration task currently holds this file. Directories are never locked —
 * a migration targets a single file.
 */
export function isNodeLocked(node: BrowsedVideo): boolean {
    return !node.isDir && node.isLocked;
}

/**
 * The directory an entry actually sits in, in DB path format.
 *
 * For a listing that is the directory on screen. A search result may have come from any
 * depth below it, and carries that offset in `relativePath` — an entry's own location is
 * the only thing an operation on it may be told about.
 */
export function nodeDirectory(currentPath: string[], node: BrowsedVideo): string {
    return [currentPath.join('/'), node.relativePath]
        .filter(part => !!part)
        .join('/');
}

export function formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export function formatDuration(seconds: number | null | undefined): string {
    const total = seconds ?? 0;
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    if (h > 0) {
        return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
}