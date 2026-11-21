// Apollo Client derives result types from the default errorPolicy, so the default options below
// must be declared here too; otherwise results would be typed as if errors always throw.
declare module '@apollo/client' {
  export namespace ApolloClient {
    export namespace DeclareDefaultOptions {
      interface WatchQuery {
        errorPolicy: 'all';
      }
      interface Query {
        errorPolicy: 'all';
      }
      interface Mutate {
        errorPolicy: 'all';
      }
    }
  }
}

/*
  Kept apart from app.config so the specs can apply it to their testing client without
  pulling in the whole app; otherwise they would run on Apollo's defaults (cache-first,
  errors thrown), which this app never uses.
*/
export const APOLLO_DEFAULT_OPTIONS = {
  watchQuery: {
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
  },
  query: {
    fetchPolicy: 'network-only',
    errorPolicy: 'all',
  },
  mutate: {
    errorPolicy: 'all',
  },
  subscribe: {
    errorPolicy: 'all',
  },
} as const;
