import { gql } from 'apollo-angular';

export const SEARCH_VIDEOS = gql`
  query SearchVideos($input: VideoSearchInput!) {
    SearchVideos(input: $input) {
      pagination {
        size
        totalCount
        currentPageNumber
      }
      videos {
        id
        name
        author
        viewCount
        loved
        lastViewTime
        lastModifyTime
        thumbnail
        duration
        isLocked
      }
    }
  }
`;

export const GET_TOP_TAGS = gql`
  query GetTopTags {
    getTopTags {
      name
      count
    }
  }
`

export const GET_TOP_TAGS_AS_SUGGESTION = gql`
  query GetTopTagsAsSuggestion {
    getTopTags {
      name
    }
  }
`;

export const GET_VIDEO_BY_ID = gql`
  query GetVideoById($videoId: ID!) {
    getVideoById(videoId: $videoId) {
      id
      name
      tags {
        name
      }
      author
      viewCount
      loved
      lastViewTime
      lastModifyTime
      introduction
      duration
      seriesName
      seriesOrder
      isLocked
    }
  }
`;

export const SEARCH_SERIES_BY_PREFIX = gql`
  query SearchSeriesByPrefix($prefix: String!, $limit: Int!) {
    searchSeriesByPrefix(prefix: $prefix, limit: $limit)
  }
`;

export const GET_SERIES_VIDEOS = gql`
  query GetSeriesVideos($name: String!) {
    getSeriesVideos(name: $name) {
      id
      name
      seriesOrder
      thumbnail
      duration
      isLocked
    }
  }
`;

export const GET_SUGGESTIONS = gql`
  query GetSuggestions($input: SuggestionInput!) {
    getSuggestions(input: $input)
  }
`;

export const BROWSE_DIRECTORY = gql`
  query BrowseDirectory($input: RelativePathInput!) {
    browseDirectory(input: $input) {
      node {
        id
        isDir
        name
        tags {
          name
        }
        author
        loved
        lastModifyTime
        introduction
        size
        duration
        seriesName
        seriesOrder
        isLocked
        relativePath
      }
    }
  }
`;

export const SEARCH_IN_DIRECTORY = gql`
  query SearchInDirectory($input: SearchInDirectoryInput!) {
    searchInDirectory(input: $input) {
      node {
        id
        isDir
        name
        tags {
          name
        }
        author
        loved
        lastModifyTime
        introduction
        size
        duration
        seriesName
        seriesOrder
        isLocked
        relativePath
      }
    }
  }
`;

export const GET_DIRECTORY_METADATA = gql`
  query GetDirectoryMetadata($input: RelativePathInput!) {
    getDirectoryMetadata(input: $input) {
      totalSize
      lastModifiedTime
    }
  }
`;
