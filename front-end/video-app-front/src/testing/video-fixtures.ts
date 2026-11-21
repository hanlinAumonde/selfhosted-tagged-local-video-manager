import { BrowseDirectoryDetail, SearchedVideo, VideoDetail } from '../app/shared/models/GQL-result.model';

/** A video as `getVideoById` returns it, for the player page. */
export function aVideoDetail(overrides: Partial<VideoDetail> = {}): VideoDetail {
  const id = overrides.id ?? `video-${nextVideoNumber++}`;
  return {
    __typename: 'Video',
    id,
    name: id,
    author: '',
    viewCount: 0,
    loved: false,
    lastViewTime: 0,
    lastModifyTime: 0,
    introduction: '',
    duration: 60,
    seriesName: null,
    seriesOrder: null,
    isLocked: false,
    tags: [],
    ...overrides,
  };
}

/** A video as the search results, the home page and the series panel list it. */
export function aSearchedVideo(overrides: Partial<SearchedVideo> = {}): SearchedVideo {
  const id = overrides.id ?? `video-${nextVideoNumber++}`;
  return {
    __typename: 'Video',
    id,
    name: id,
    author: '',
    viewCount: 0,
    loved: false,
    lastViewTime: 0,
    lastModifyTime: 0,
    thumbnail: null,
    duration: 60,
    isLocked: false,
    ...overrides,
  };
}

type BrowseNode = BrowseDirectoryDetail[number];
type VideoNode = BrowseNode['node'];

let nextVideoNumber = 1;

/** A file-browser row holding a video; pass `isDir: true` for a directory row. */
export function aBrowseNode(overrides: Partial<VideoNode> = {}): BrowseNode {
  const id = overrides.id ?? `video-${nextVideoNumber++}`;
  return {
    __typename: 'FileBrowseNode',
    node: {
      __typename: 'Video',
      id,
      isDir: false,
      name: `${id}.mp4`,
      author: '',
      loved: false,
      lastModifyTime: 0,
      introduction: '',
      size: 1000,
      duration: 60,
      seriesName: null,
      seriesOrder: null,
      isLocked: false,
      relativePath: null,
      tags: [],
      ...overrides,
    },
  };
}
