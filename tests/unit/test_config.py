"""Unit tests for config.py utility methods."""

import pytest

from src import config
from pydantic import ValidationError

from src.config import S3HandlerConfig, Settings, get_settings

pytestmark = pytest.mark.unit


class TestSettingsUtilities:
    def test_get_all_host_paths(self, test_settings: Settings):
        paths = test_settings.get_all_host_paths()
        assert isinstance(paths, set)
        assert "/test/videos" in paths

    def test_get_host_path(self, test_settings: Settings):
        result = test_settings.get_host_path("Test-category", "Test-resource")
        assert result == "/test/videos"

    def test_find_category_by_host_path_exact(self, test_settings: Settings):
        assert test_settings.find_category_by_host_path("/test/videos") == "Test-category"

    def test_find_category_by_host_path_subpath(self, test_settings: Settings):
        assert test_settings.find_category_by_host_path("/test/videos/sub/file.mp4") == "Test-category"

    def test_find_category_by_host_path_no_match(self, test_settings: Settings):
        assert test_settings.find_category_by_host_path("/unrelated/path") is None

    def test_get_settings_not_initialized(self, monkeypatch):
        monkeypatch.setattr(config, "_settings", None)
        with pytest.raises(RuntimeError, match="Settings have not been initialized"):
            get_settings()


# ----------------------------------------------------------------------
# ------------- Typed, per-category handler configuration ---------------
# ----------------------------------------------------------------------


S3_MOUNT = {
    "endpoint_url": "http://localhost:9999",
    "access_key": "test-key",
    "secret_key": "test-secret",
    "bucket": "video-app",
}


class TestHandlerConfigResolution:
    def test_absent_category_resolves_to_the_local_fs_config(self):
        settings = Settings.model_validate({"resource_paths": {"Cat": {"P1": "/data/p1"}}})

        # The default belongs to the config layer; the dispatcher only looks up
        # whatever type it is handed.
        assert settings.get_handler_config("Cat").type == "local_fs"

    def test_declared_s3_category_keeps_its_mounts_typed(self):
        settings = Settings.model_validate(
            {
                "resource_paths": {"S3-cat": {"Resource-1": "/"}},
                "handler_config": {"S3-cat": {"type": "s3", "mounts": {"Resource-1": S3_MOUNT}}},
            }
        )

        config = settings.get_handler_config("S3-cat")

        assert config.type == "s3"
        assert isinstance(config.mounts["Resource-1"], S3HandlerConfig)
        assert config.mounts["Resource-1"].bucket == "video-app"

    def test_unknown_type_is_rejected_while_settings_load(self):
        # A typo in the type name must stop the process at startup, not surface
        # as a missing handler on someone's first request.
        with pytest.raises(ValidationError):
            Settings.model_validate(
                {
                    "resource_paths": {"Cat": {"P1": "/data/p1"}},
                    "handler_config": {"Cat": {"type": "carrier_pigeon", "mounts": {}}},
                }
            )

    def test_s3_category_missing_its_mounts_is_rejected(self):
        # An S3 category with nowhere to connect is not a usable configuration.
        with pytest.raises(ValidationError):
            Settings.model_validate(
                {
                    "resource_paths": {"S3-cat": {"Resource-1": "/"}},
                    "handler_config": {"S3-cat": {"type": "s3", "mounts": {}}},
                }
            )
