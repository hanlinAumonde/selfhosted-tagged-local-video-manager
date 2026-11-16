from typing import AsyncGenerator

import strawberry
from src.resolvers import subscription_resolver, migration_resolver
from src.schema.types.fileBrowse_type import (
    BatchOperationStatus,
    VideosBatchOperationInput,
)
from src.schema.types.migration_type import (
    MigrationBatchActionInput,
    MigrationBatchProgress,
    MigrationProgressStatus,
    MigrationTaskActionInput,
)

@strawberry.type
class Subscription:
    @strawberry.subscription
    async def batchUpdateSubscription(
        self, info: strawberry.Info, input: VideosBatchOperationInput
    ) -> AsyncGenerator[BatchOperationStatus, None]:
        async for status in subscription_resolver.resolve_batch_operations(input=input, update=True, info=info):
            yield status

    @strawberry.subscription
    async def batchDeleteSubscription(
        self, info: strawberry.Info, input: VideosBatchOperationInput
    ) -> AsyncGenerator[BatchOperationStatus, None]:
        async for status in subscription_resolver.resolve_batch_operations(input=input, update=False, info=info):
            yield status

    @strawberry.subscription
    async def migrationProgressSubscription(
        self, info: strawberry.Info, input: MigrationTaskActionInput
    ) -> AsyncGenerator[MigrationProgressStatus, None]:
        async for status in migration_resolver.resolve_migration_progress(input=input, info=info):
            yield status

    @strawberry.subscription
    async def migrationRetrySubscription(
        self, info: strawberry.Info, input: MigrationTaskActionInput
    ) -> AsyncGenerator[MigrationProgressStatus, None]:
        async for status in migration_resolver.resolve_migration_retry(input=input, info=info):
            yield status

    @strawberry.subscription
    async def migrationBatchProgress(
        self, info: strawberry.Info, input: MigrationBatchActionInput
    ) -> AsyncGenerator[MigrationBatchProgress, None]:
        async for event in migration_resolver.resolve_migration_batch_progress(input=input, info=info):
            yield event
