import { TestBed } from '@angular/core/testing';
import { Apollo } from 'apollo-angular';
import { ApolloTestingController } from 'apollo-angular/testing';

import { APOLLO_DEFAULT_OPTIONS } from '../app/core/graphql/apollo-default-options';

/**
 * The testing controller, with the client set up as the app sets it up. Call after
 * configuring a module that imports ApolloTestingModule.
 */
export function apolloAsInTheApp(): ApolloTestingController {
  TestBed.inject(Apollo).client.defaultOptions = APOLLO_DEFAULT_OPTIONS;
  return TestBed.inject(ApolloTestingController);
}
