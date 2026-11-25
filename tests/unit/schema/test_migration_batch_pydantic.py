"""GraphQL input contracts of the batch migration API."""

import pytest
from pydantic import ValidationError

from src.config import Settings

from src.schema.types.pydantic_types.migration_type import (
    CreateMigrationBatchInputModel,
    MigrationBatchPreflightInputModel,
)

pytestmark = pytest.mark.unit

TARGET = {"relativePath": "Test-category/Test-resource", "parsedPath": None}


def _ids(count: int) -> list[str]:
    return [f"{i:024x}" for i in range(count)]


class TestBatchSourceVideoIds:
    def test_an_empty_source_list_is_rejected(self, test_settings):
        """
        Scenario: a batch needs at least one file
          Given a batch migration input with sourceVideoIds []
          When it is validated
          Then a validation error is raised
        """
        with pytest.raises(ValidationError):
            MigrationBatchPreflightInputModel(source_video_ids=[], target_dir_relative_path=TARGET)

    def test_duplicate_source_ids_are_rejected(self, test_settings):
        """
        Scenario: the same file listed twice is a client mistake
          Given a batch migration input with sourceVideoIds ["v1", "v2", "v1"]
          When it is validated
          Then a validation error is raised
        """
        with pytest.raises(ValidationError):
            MigrationBatchPreflightInputModel(
                source_video_ids=["v1", "v2", "v1"], target_dir_relative_path=TARGET
            )

    def test_more_than_500_source_ids_are_rejected(self, test_settings):
        """
        Scenario: one request cannot create an unbounded batch
          Given a batch migration input with 501 distinct sourceVideoIds
          When it is validated
          Then a validation error is raised
          And with exactly 500 distinct ids it is accepted
        """
        with pytest.raises(ValidationError):
            CreateMigrationBatchInputModel(source_video_ids=_ids(501), target_dir_relative_path=TARGET)

        accepted = CreateMigrationBatchInputModel(source_video_ids=_ids(500), target_dir_relative_path=TARGET)
        assert len(accepted.source_video_ids) == 500


class TestBatchConflictStrategy:
    def test_an_unknown_conflict_strategy_is_rejected(self, test_settings):
        """
        Scenario: only the three known strategies are accepted
          Given a create-batch input with conflictStrategy "merge"
          When it is validated
          Then a validation error is raised
        """
        with pytest.raises(ValidationError):
            CreateMigrationBatchInputModel(
                source_video_ids=_ids(2), target_dir_relative_path=TARGET, conflict_strategy="merge"
            )


class TestConfiguredBatchSize:
    def test_the_batch_size_limit_comes_from_the_configuration(self, test_settings, monkeypatch):
        """
        Scenario: the most sources one batch may hold is a setting
          Given validation.migration_batch_max_size is 3
          When a batch migration input with 4 distinct sourceVideoIds is validated
          Then a validation error is raised
          And with exactly 3 distinct ids it is accepted
        """
        payload = test_settings.model_dump()
        payload["validation"]["migration_batch_max_size"] = 3
        monkeypatch.setattr("src.config._settings", Settings.model_validate(payload))

        with pytest.raises(ValidationError):
            CreateMigrationBatchInputModel(source_video_ids=_ids(4), target_dir_relative_path=TARGET)

        accepted = CreateMigrationBatchInputModel(source_video_ids=_ids(3), target_dir_relative_path=TARGET)
        assert len(accepted.source_video_ids) == 3
