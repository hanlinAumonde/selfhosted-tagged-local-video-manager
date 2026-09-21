import pytest

from src.config import Settings
from src.features.browsing.dir_metadata_service import DirMetadataService
from src.features.migration.migration_service import MigrationService
from src.platform.cache.cache_service import CacheService
from src.platform.storage.resource_handler_service import ResourceHandlerService


@pytest.fixture
def migration_svc(
    fs_settings: Settings,
    local_resource_handler_service: ResourceHandlerService,
    local_cache_service: CacheService,
) -> MigrationService:
    dir_meta = DirMetadataService(
        settings=fs_settings,
        resource_handler_service=local_resource_handler_service,
        cache_service=local_cache_service,
    )
    return MigrationService(
        resource_handler_service=local_resource_handler_service,
        dir_metadata_service=dir_meta,
    )


@pytest.fixture
def two_cat_migration_svc(
    two_category_settings: Settings,
    two_cat_handler_service: ResourceHandlerService,
    two_cat_cache_service: CacheService,
) -> MigrationService:
    dir_meta = DirMetadataService(
        settings=two_category_settings,
        resource_handler_service=two_cat_handler_service,
        cache_service=two_cat_cache_service,
    )
    return MigrationService(
        resource_handler_service=two_cat_handler_service,
        dir_metadata_service=dir_meta,
    )
