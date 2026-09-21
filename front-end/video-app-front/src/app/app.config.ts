import { ApplicationConfig, inject, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';
import {
  HTTP_INTERCEPTORS,
  provideHttpClient,
  withInterceptorsFromDi
} from '@angular/common/http';
import { provideApollo } from 'apollo-angular';
import { environment } from '../environments/environment';
import { routes } from './app.routes';
import { HttpLink } from 'apollo-angular/http';
import { ApolloLink, InMemoryCache } from '@apollo/client';
import { ImageRequestInterceptor } from './shared/interceptor/ImageRequest.interceptor';
import { createClient } from 'graphql-ws';
import { GraphQLWsLink } from '@apollo/client/link/subscriptions';
import { getMainDefinition } from '@apollo/client/utilities';
import { Kind, OperationTypeNode } from 'graphql';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // Fetch is the default backend as of v22, so `withFetch()` is no longer needed.
    provideHttpClient(withInterceptorsFromDi()),
    {
      provide: HTTP_INTERCEPTORS,
      useClass: ImageRequestInterceptor,
      multi: true
    },
    provideApollo(() => {
      const httpLink = inject(HttpLink)
      const http = httpLink.create({ uri: environment.backend_api + "/graphql" });
      const ws = new GraphQLWsLink(
        createClient({
          url: environment.backend_ws_api +  "/graphql",
        }),
      );
      const link = ApolloLink.split(
        ({ query }) => {
          const definition = getMainDefinition(query);
          return (
            definition.kind === Kind.OPERATION_DEFINITION &&
            definition.operation === OperationTypeNode.SUBSCRIPTION
          );
        }, ws, http
      )
      return {
        link: link,
        cache: new InMemoryCache({
          typePolicies: {
            Query: {
              fields: {
                // Search result pagination merging strategy
                SearchVideos: {
                  keyArgs: ['input', ['titleKeyword', 'author', 'tags', 'sortBy']],
                  merge(existing, incoming) {
                    return incoming; // Replace each time, do not merge paginated results
                  },
                },
              },
            },
          },
        }),
        defaultOptions: {
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
          }
        },
      };
    }),
  ],
};
