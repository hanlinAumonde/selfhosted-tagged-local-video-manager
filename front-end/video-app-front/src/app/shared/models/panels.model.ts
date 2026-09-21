import { UpdateVideoMetadataInput } from '../../core/graphql/generated/graphql';
import { BrowsedVideo, VideoDetail } from './GQL-result.model';


export type VideoEditPanelMode = 'full' | 'filter';

export interface BatchPanelVideoItem {
  id: string;
  name: string;
  seriesName?: string | null;
  seriesOrder?: number | null;
}

export interface BatchPanelData {
  mode: 'videos' | 'directory';
  videos?: Set<string>;
  videoItems?: ReadonlyArray<BatchPanelVideoItem>;
  selectedDirectoryPath?: string;
}

export interface EditFormState {
  name: string;
  author: string;
  loved: boolean;
  introduction: string;
  tags: string[];
}

export type SaveEventData = UpdateVideoMetadataInput | string[];

// VideoEditPanel requires: id, name, author, loved, introduction, tags
export type EditableVideo = VideoDetail | BrowsedVideo;

export interface VideoEditPanelData {
  mode: VideoEditPanelMode;
  video?: EditableVideo;
  selectedTags?: string[];
}


export interface AuthorSuggestion {
  value: string;
}

export interface TagSuggestion {
  value: string;
}

export enum DeleteType {
  Single = 'single',
  Batch = 'batch',
  Directory = 'directory'
}

export interface DeleteCheckPanelData {
  deleteType: DeleteType;
  videoCount?: number;
  videoIds?: Set<string>;
  directoryPath?: string;
}

export type SeriesAction = 'set' | 'clear';

/** Which of a batch tag edit's two lists a chip belongs to. */
export type TagDirection = 'add' | 'remove';

export interface NewFolderPanelData {
  /** The directory the folder goes into, in DB path format. */
  parentPath: string;
}

export interface SearchPanelData {
  /** The directory the search runs in, in DB path format. */
  directoryPath: string;
}

/**
 * What the search panel asks for. Blank fields are not filters — the panel always sends
 * all three, and the backend ignores the ones that would narrow nothing.
 */
export interface DirectorySearchCriteria {
  name: string;
  author: string;
  tags: string[];
}

export interface MigrationPanelData {
  sourceVideoId: string;
  sourceVideoName: string;
  sourceFileSize: number;
  sourceCurrentDir: string;
}