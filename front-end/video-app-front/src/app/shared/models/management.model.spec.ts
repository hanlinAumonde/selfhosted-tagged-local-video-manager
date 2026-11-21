import { aBrowseNode } from '../../../testing/video-fixtures';
import { selectableVideoIds } from './management.model';

describe('selectableVideoIds', () => {
  it('leaves out folders and videos a migration is holding', () => {
    /*
      Given a listing with folder "clips", videos "v1" and "v2" and video "busy" held by a migration
      When the selectable videos are asked for
      Then they are "v1" and "v2"
    */
    const listing = [
      aBrowseNode({ id: 'clips', isDir: true }),
      aBrowseNode({ id: 'v1' }),
      aBrowseNode({ id: 'busy', isLocked: true }),
      aBrowseNode({ id: 'v2' }),
    ];

    expect(selectableVideoIds(listing)).toEqual(['v1', 'v2']);
  });
});
