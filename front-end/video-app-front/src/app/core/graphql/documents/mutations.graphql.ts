import { gql } from 'apollo-angular';

export const UPDATE_VIDEO_METADATA = gql`
  mutation UpdateVideoMetadata($input: UpdateVideoMetadataInput!) {
    updateVideoMetadata(input: $input) {
      success
      video {
        id
        name
        tags {
          name
        }
        author
        loved
        introduction
        seriesName
        seriesOrder
      }
    }
  }
`;

export const RECORD_VIDEO_VIEW = gql`
  mutation RecordVideoView($videoId: ID!) {
    recordVideoView(videoId: $videoId) {
      success
      video {
        id
        viewCount
        lastViewTime
      }
    }
  }
`;

export const CREATE_DIRECTORY = gql`
  mutation CreateDirectory($input: CreateDirectoryInput!) {
    createDirectory(input: $input) {
      success
      name
      path
    }
  }
`;

export const DELETE_VIDEO = gql`
  mutation DeleteVideo($videoId: ID!) {
    deleteVideo(videoId: $videoId) {
      success
      video {
        id
      }
    }
  }
`;