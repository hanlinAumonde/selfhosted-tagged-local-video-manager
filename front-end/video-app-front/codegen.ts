import type { CodegenConfig } from '@graphql-codegen/cli';
import { environment } from './src/environments/environment.development'

const config: CodegenConfig = {
  schema: environment.backend_api + "/graphql",

  documents: ['src/**/*.graphql.ts'],

  generates: {
    './src/app/core/graphql/generated/graphql.ts': {
      plugins: [
        'typescript', 
        'typescript-operations', 
        'typescript-apollo-angular', // generate Apollo Angular service
      ],
      config: {
        withHooks: false,
        withComponent: false,
        withHOC: false,
        addExplicitOverride: true,
        documentMode: 'documentNode',
        scalars: {
          BigInt: 'string',
        },
      },
    },
  },
};

export default config;
