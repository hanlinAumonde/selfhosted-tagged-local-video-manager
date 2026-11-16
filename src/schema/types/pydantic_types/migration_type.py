from pydantic import BaseModel, field_validator

from src.schema.types.pydantic_types.fileBrowe_type import RelativePathInputModel

#: Files one batch request may move. Each is checked and inserted one by one, so this
#: bounds how long a single request takes.
MAX_BATCH_SIZE = 500


def _validate_conflict_strategy(v: str | None) -> str | None:
    if v is not None and v not in ("overwrite", "rename", "skip"):
        raise ValueError("conflict_strategy must be 'overwrite', 'rename', 'skip', or null")
    return v


class MigrationPreflightInputModel(BaseModel):
    source_video_id: str
    target_dir_relative_path: RelativePathInputModel


class CreateMigrationTaskInputModel(BaseModel):
    source_video_id: str
    target_dir_relative_path: RelativePathInputModel
    conflict_strategy: str | None = None

    @field_validator("conflict_strategy", mode="after")
    @classmethod
    def validate_strategy(cls, v: str | None) -> str | None:
        return _validate_conflict_strategy(v)


class MigrationBatchPreflightInputModel(BaseModel):
    source_video_ids: list[str]
    target_dir_relative_path: RelativePathInputModel

    @field_validator("source_video_ids", mode="after")
    @classmethod
    def validate_source_video_ids(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("a batch needs at least one source video")
        if len(v) > MAX_BATCH_SIZE:
            raise ValueError(f"a batch can move at most {MAX_BATCH_SIZE} videos")
        if len(set(v)) != len(v):
            raise ValueError("source video ids must not repeat")
        return v


class CreateMigrationBatchInputModel(MigrationBatchPreflightInputModel):
    conflict_strategy: str | None = None

    @field_validator("conflict_strategy", mode="after")
    @classmethod
    def validate_strategy(cls, v: str | None) -> str | None:
        return _validate_conflict_strategy(v)


class MigrationTaskActionInputModel(BaseModel):
    task_id: str


class MigrationBatchActionInputModel(BaseModel):
    batch_id: str


class MigrationTaskQueryInputModel(BaseModel):
    status_filter: list[str] | None = None
    page: int = 1
    page_size: int = 20
    batch_id: str | None = None

    @field_validator("page", mode="after")
    @classmethod
    def validate_page(cls, v: int) -> int:
        if v < 1:
            raise ValueError("page must be >= 1")
        return v

    @field_validator("page_size", mode="after")
    @classmethod
    def validate_page_size(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("page_size must be between 1 and 100")
        return v
