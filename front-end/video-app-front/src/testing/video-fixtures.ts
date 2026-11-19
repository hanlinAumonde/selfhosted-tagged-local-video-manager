import { BrowseDirectoryDetail } from '../app/shared/models/GQL-result.model';

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
