"""Tests for migration pydantic input models."""

import pytest

from src.config import Settings

from src.schema.types.pydantic_types.migration_type import (
    CreateMigrationTaskInputModel,
    MigrationTaskQueryInputModel,
)

pytestmark = pytest.mark.unit


def _use_settings(monkeypatch, test_settings: Settings, section: str, **values) -> None:
    payload = test_settings.model_dump()
    payload[section].update(values)
    monkeypatch.setattr("src.config._settings", Settings.model_validate(payload))


class TestCreateMigrationTaskInputModel:
    def test_valid_conflict_strategies(self, test_settings):
        for strategy in ("overwrite", "rename", "skip", None):
            model = CreateMigrationTaskInputModel(
                source_video_id="507f1f77bcf86cd799439011",
                target_dir_relative_path={"relativePath": "Test-category/Test-resource", "parsedPath": None},
                conflict_strategy=strategy,
            )
            assert model.conflict_strategy == strategy

    def test_invalid_conflict_strategy(self, test_settings):
        with pytest.raises(ValueError, match="conflict_strategy must be"):
            CreateMigrationTaskInputModel(
                source_video_id="507f1f77bcf86cd799439011",
                target_dir_relative_path={"relativePath": "Test-category/Test-resource", "parsedPath": None},
                conflict_strategy="invalid",
            )


class TestMigrationTaskQueryInputModel:
    def test_valid_defaults(self):
        model = MigrationTaskQueryInputModel()
        assert model.page == 1
        assert model.page_size == 20
        assert model.status_filter is None

    def test_page_below_one_raises(self):
        with pytest.raises(ValueError, match="page must be >= 1"):
            MigrationTaskQueryInputModel(page=0)

    def test_page_size_too_small_raises(self):
        with pytest.raises(ValueError, match="page_size must be between"):
            MigrationTaskQueryInputModel(page_size=0)

    def test_page_size_too_large_raises(self):
        with pytest.raises(ValueError, match="page_size must be between"):
            MigrationTaskQueryInputModel(page_size=101)

    def test_status_filter(self):
        model = MigrationTaskQueryInputModel(status_filter=["PENDING", "PROCESSING"])
        assert model.status_filter == ["PENDING", "PROCESSING"]


class TestConfiguredPageSize:
    def test_the_largest_page_size_comes_from_the_configuration(self, test_settings, monkeypatch):
        """
        Scenario: the largest page a client may ask for is a setting
          Given validation.migration_page_size_max is 10
          When a migration task query asks for page_size 11
          Then a validation error is raised
          And with page_size 10 it is accepted
        """
        _use_settings(monkeypatch, test_settings, "validation", migration_page_size_max=10)

        with pytest.raises(ValueError, match="page_size must be between"):
            MigrationTaskQueryInputModel(page_size=11)

        assert MigrationTaskQueryInputModel(page_size=10).page_size == 10
