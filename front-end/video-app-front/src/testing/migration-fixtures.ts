import { MigrationStatusEnum } from '../app/core/graphql/generated/graphql';
import {
  MigrationBatchSummaryDetail,
  MigrationProgressDetail,
  MigrationTaskItem,
} from '../app/shared/models/GQL-result.model';

let nextTaskNumber = 1;

/** A task moving `sourcePath` to `targetPath`; only what a test cares about needs passing. */
export function aMigrationTask(overrides: Partial<MigrationTaskItem> = {}): MigrationTaskItem {
  const id = overrides.id ?? `task-${nextTaskNumber++}`;
  const sourcePath = overrides.sourcePath ?? `local/src/${id}.mp4`;
  const targetPath = overrides.targetPath ?? `local/dst/${id}.mp4`;
  return {
    __typename: 'MigrationTask',
    id,
    sourcePath,
    sourceCategory: 'local',
    targetPath,
    targetCategory: 'local',
    fileName: sourcePath.slice(sourcePath.lastIndexOf('/') + 1),
    fileSize: '1000',
    bytesTransferred: '0',
    status: MigrationStatusEnum.Pending,
    errorMessage: null,
    failedStep: null,
    conflictStrategy: null,
    renamedTargetPath: null,
    createdAt: 0,
    updatedAt: 0,
    completedAt: null,
    batchId: null,
    ...overrides,
  };
}

export function aProgressFrame(
  taskId: string,
  status: MigrationStatusEnum,
  bytesTransferred = 0,
): MigrationProgressDetail {
  return {
    __typename: 'MigrationProgressStatus',
    taskId,
    status,
    bytesTransferred: String(bytesTransferred),
    totalBytes: '1000',
    progressPercentage: bytesTransferred / 10,
    message: null,
  };
}

export function aBatchSummary(
  batchId: string,
  counts: Partial<Omit<MigrationBatchSummaryDetail, 'batchId'>> = {},
): MigrationBatchSummaryDetail {
  return {
    __typename: 'MigrationBatchSummary',
    batchId,
    total: 0,
    active: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
    ...counts,
  };
}
