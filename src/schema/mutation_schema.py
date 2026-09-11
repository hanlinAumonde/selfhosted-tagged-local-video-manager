import strawberry

from src.schema.types.fileBrowse_type import DirectoryMutationResult, VideoMutationResult
from src.schema.types.migration_type import (
    MigrationPreflightResult,
    MigrationTaskMutationResult,
)
from src.resolvers import mutation_resolver, migration_resolver

@strawberry.type
class Mutation:
    updateVideoMetadata: VideoMutationResult = strawberry.mutation(resolver=mutation_resolver.resolve_update_video_metadata)

    recordVideoView: VideoMutationResult = strawberry.mutation(resolver=mutation_resolver.resolve_record_video_view)

    deleteVideo: VideoMutationResult = strawberry.mutation(resolver=mutation_resolver.resolve_delete_video)

    createDirectory: DirectoryMutationResult = strawberry.mutation(resolver=mutation_resolver.resolve_create_directory)

    migrationPreflight: MigrationPreflightResult = strawberry.mutation(resolver=migration_resolver.resolve_migration_preflight)

    createMigrationTask: MigrationTaskMutationResult = strawberry.mutation(resolver=migration_resolver.resolve_create_migration_task)

    cancelMigrationTask: MigrationTaskMutationResult = strawberry.mutation(resolver=migration_resolver.resolve_cancel_migration_task)
