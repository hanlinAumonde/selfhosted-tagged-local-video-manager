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


# ----------------------------------------------------------------------
# ----------------------- Cache configuration ---------------------------
# ----------------------------------------------------------------------


class TestCacheConfig:
    def test_yaml_shaped_cache_config_is_parsed(self):
        # Given a cache_config dict shaped like config.yaml, with cache_type "redis",
        #   a key_prefix, ttl.dir_metadata, redis.url / socket_timeout and cachetools.max_size
        # When Settings are validated from it
        # Then every one of those values is readable from settings.cache_config
        settings = Settings.model_validate({
            "cache_config": {
                "cache_type": "redis",
                "key_prefix": "video-app",
                "ttl": {"dir_metadata": 120},
                "redis": {"url": "redis://cache:6379/1", "socket_timeout": 0.5},
                "cachetools": {"max_size": 3000},
            }
        })

        cache = settings.cache_config
        assert cache.cache_type == "redis"
        assert cache.key_prefix == "video-app"
        assert cache.ttl.dir_metadata == 120
        assert cache.redis.url == "redis://cache:6379/1"
        assert cache.redis.socket_timeout == 0.5
        assert cache.cachetools.max_size == 3000

    def test_omitted_cache_config_falls_back_to_cachetools(self):
        # Given settings that contain no cache_config at all
        # When Settings are validated
        # Then cache_type is "cachetools", so nothing tries to reach a Redis that was never configured
        settings = Settings.model_validate({})
        assert settings.cache_config.cache_type == "cachetools"

    def test_unknown_cache_type_is_rejected_while_settings_load(self):
        # Given a cache_config whose cache_type is "memcached"
        # When Settings are validated
        # Then a ValidationError is raised at load time rather than on the first cache call
        with pytest.raises(ValidationError):
            Settings.model_validate({"cache_config": {"cache_type": "memcached"}})
