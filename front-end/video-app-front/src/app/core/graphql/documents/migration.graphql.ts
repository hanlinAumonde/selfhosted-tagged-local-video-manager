import { gql } from 'apollo-angular';

export const MIGRATION_PREFLIGHT = gql`
  mutation MigrationPreflight($input: MigrationPreflightInput!) {
    migrationPreflight(input: $input) {
      valid
      sourceFileSize
      conflictExists
      spaceAvailable
      spaceSufficient
      alreadyMigrating
      sameLocation
      errorMessage
    }
  }
`;

export const CREATE_MIGRATION_TASK = gql`
  mutation CreateMigrationTask($input: CreateMigrationTaskInput!) {
    createMigrationTask(input: $input) {
      success
      errorMessage
      task {
        id
        sourcePath
        sourceCategory
        targetPath
        targetCategory
        fileName
        fileSize
        bytesTransferred
        status
        errorMessage
        failedStep
        conflictStrategy
        renamedTargetPath
        createdAt
        updatedAt
        completedAt
        batchId
      }
    }
  }
`;

export const CANCEL_MIGRATION_TASK = gql`
  mutation CancelMigrationTask($input: MigrationTaskActionInput!) {
    cancelMigrationTask(input: $input) {
      success
      errorMessage
      task {
        id
        sourcePath
        targetPath
        fileName
        status
      }
    }
  }
`;

export const GET_MIGRATION_TASKS = gql`
  query GetMigrationTasks($input: MigrationTaskQueryInput!) {
    getMigrationTasks(input: $input) {
      totalCount
      page
      pageSize
      tasks {
        id
        sourcePath
        sourceCategory
        targetPath
        targetCategory
        fileName
        fileSize
        bytesTransferred
        status
        errorMessage
        failedStep
        conflictStrategy
        renamedTargetPath
        createdAt
        updatedAt
        completedAt
        batchId
      }
    }
  }
`;

export const MIGRATION_PROGRESS = gql`
  subscription MigrationProgress($input: MigrationTaskActionInput!) {
    migrationProgressSubscription(input: $input) {
      taskId
      status
      bytesTransferred
      totalBytes
      progressPercentage
      message
    }
  }
`;

export const MIGRATION_RETRY = gql`
  subscription MigrationRetry($input: MigrationTaskActionInput!) {
    migrationRetrySubscription(input: $input) {
      taskId
      status
      bytesTransferred
      totalBytes
      progressPercentage
      message
    }
  }
`;

export const MIGRATION_BATCH_PREFLIGHT = gql`
  mutation MigrationBatchPreflight($input: MigrationBatchPreflightInput!) {
    migrationBatchPreflight(input: $input) {
      valid
      totalSize
      spaceAvailable
      spaceSufficient
      items {
        sourceVideoId
        result {
          valid
          sourceFileSize
          conflictExists
          alreadyMigrating
          sameLocation
          errorMessage
        }
      }
    }
  }
`;

export const CREATE_MIGRATION_BATCH = gql`
  mutation CreateMigrationBatch($input: CreateMigrationBatchInput!) {
    createMigrationBatch(input: $input) {
      batchId
      tasks {
        id
        sourcePath
        sourceCategory
        targetPath
        targetCategory
        fileName
        fileSize
        bytesTransferred
        status
        errorMessage
        failedStep
        conflictStrategy
        renamedTargetPath
        createdAt
        updatedAt
        completedAt
        batchId
      }
      skipped {
        sourceVideoId
        reason
      }
    }
  }
`;

export const CANCEL_MIGRATION_BATCH = gql`
  mutation CancelMigrationBatch($input: MigrationBatchActionInput!) {
    cancelMigrationBatch(input: $input) {
      batchId
      total
      active
      completed
      failed
      cancelled
    }
  }
`;

export const RETRY_MIGRATION_BATCH = gql`
  mutation RetryMigrationBatch($input: MigrationBatchActionInput!) {
    retryMigrationBatch(input: $input) {
      batchId
      total
      active
      completed
      failed
      cancelled
    }
  }
`;

export const MIGRATION_BATCH_PROGRESS = gql`
  subscription MigrationBatchProgress($input: MigrationBatchActionInput!) {
    migrationBatchProgress(input: $input) {
      summary {
        batchId
        total
        active
        completed
        failed
        cancelled
      }
      task {
        taskId
        status
        bytesTransferred
        totalBytes
        progressPercentage
        message
      }
    }
  }
`;
