import { MigrationStatusEnum } from '../../core/graphql/generated/graphql';

export type ConflictStrategy = 'overwrite' | 'rename' | 'skip';

export interface MigrationTaskFilter {
  statusFilter: MigrationStatusEnum[] | null;
  page: number;
  pageSize: number;
}

export interface MigrationStatusDisplay {
  label: string;
  color: string;
  icon: string;
  isTerminal: boolean;
  isActionable: boolean;
}

export const MIGRATION_STATUS_MAP: Record<MigrationStatusEnum, MigrationStatusDisplay> = {
  [MigrationStatusEnum.Pending]:        { label: 'Pending',     color: 'text-gray-500',   icon: 'hourglass_empty', isTerminal: false, isActionable: true  },
  [MigrationStatusEnum.Processing]:     { label: 'Processing',     color: 'text-blue-500',   icon: 'file_copy',       isTerminal: false, isActionable: true  },
  [MigrationStatusEnum.ProcessDone]:    { label: 'Process Done',   color: 'text-blue-600',   icon: 'check_circle',    isTerminal: false, isActionable: false },
  [MigrationStatusEnum.Committing]:     { label: 'Committing',   color: 'text-orange-500', icon: 'sync',            isTerminal: false, isActionable: false },
  [MigrationStatusEnum.Committed]:      { label: 'Committed', color: 'text-orange-600', icon: 'check_circle',    isTerminal: false, isActionable: false },
  [MigrationStatusEnum.CleaningUp]: { label: 'Cleaning Up', color: 'text-yellow-500', icon: 'delete_sweep',    isTerminal: false, isActionable: false },
  [MigrationStatusEnum.Completed]:      { label: 'Completed',     color: 'text-green-500',  icon: 'done_all',        isTerminal: true,  isActionable: false },
  [MigrationStatusEnum.Failed]:         { label: 'Failed',       color: 'text-red-500',    icon: 'error',           isTerminal: true,  isActionable: true  },
  [MigrationStatusEnum.Cancelled]:      { label: 'Cancelled',     color: 'text-gray-400',   icon: 'cancel',          isTerminal: true,  isActionable: false },
};

export const ACTIVE_MIGRATION_STATUSES: MigrationStatusEnum[] =
  (Object.keys(MIGRATION_STATUS_MAP) as MigrationStatusEnum[])
    .filter(status => !MIGRATION_STATUS_MAP[status].isTerminal);

export function isMigrationTerminal(status: MigrationStatusEnum): boolean {
  return MIGRATION_STATUS_MAP[status].isTerminal;
}

/** DB-format paths are '/'-joined, so the parent directory is a prefix cut. */
export function parentDirectoryOf(path: string): string {
  const cut = path.lastIndexOf('/');
  return cut < 0 ? '' : path.slice(0, cut);
}
