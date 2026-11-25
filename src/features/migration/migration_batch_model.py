from beanie import Document


class MigrationBatchModel(Document):
    target_dir: str
    target_category: str
    conflict_strategy: str | None = None
    created_at: float

    class Settings:
        name = "migration_batches"