import time
from typing import Callable

from beanie import init_beanie
from pymongo import AsyncMongoClient
import pytest_asyncio
from testcontainers.core.container import LogMessageWaitStrategy
from testcontainers.mongodb import MongoDbContainer
import pytest

from src import config
from src.features.browsing.dir_metadata import DirMetadataModel
from src.features.migration.migration_task import MigrationTaskModel, TaskStatus
from src.config import Settings
from src.features.catalog.series import SeriesModel
from src.features.catalog.video_tag import VideoTagModel
from src.features.catalog.video import VideoModel

# -----------------------------------------------------------------------
# ---------------------- Infrastructure fixtures -------------------------
# -----------------------------------------------------------------------

@pytest.fixture(scope="session")
def mongo_container():
    """Start a MongoDB testcontainer for the entire test session."""
    container = (
        MongoDbContainer(
            image="mongo:latest",
            username="test",
            password="test",
            dbname="test_video_tag_db",
        )
    )
    with container as mongo:
        mongo.waiting_for(LogMessageWaitStrategy('ready'))
        yield mongo


@pytest.fixture(scope="session")
def test_settings(mongo_container: MongoDbContainer) -> Settings:
    """Create Settings instance pointing to the test MongoDB."""
    return Settings.model_validate({
        "resource_paths": {
            "Test-category": {"Test-resource": "/test/videos"},
        },
        "mongo": {
            "host": mongo_container.get_container_host_ip(),
            "port": int(mongo_container.get_exposed_port(27017)),
            "database": mongo_container.dbname,
            "username": mongo_container.username,
            "password": mongo_container.password,
        },
    })


@pytest.fixture(autouse=True)
def mock_get_settings(test_settings: Settings, monkeypatch):
    original = config._settings
    config._settings = test_settings
    yield
    config._settings = original


# -----------------------------------------------------------------------
# ---------------------- Database fixtures --------------------------------
# -----------------------------------------------------------------------

@pytest_asyncio.fixture
async def init_db(mock_get_settings, test_settings: Settings):
    """Initialize Beanie with test MongoDB; clean up all collections after each test."""
    mongo_config = test_settings.mongo
    mongo_uri = "mongodb://"
    mongo_host_port = f"{mongo_config.host}:{mongo_config.port}"
    if mongo_config.username and mongo_config.password:
        mongo_uri += f"{mongo_config.username}:{mongo_config.password}@" + mongo_host_port + f"/{mongo_config.database}" + f"?authSource=admin"
    else:
        mongo_uri += mongo_host_port
    print(f"Connecting to MongoDB at {mongo_uri}")
    client = AsyncMongoClient(mongo_uri)
    await init_beanie(database=client.get_database(mongo_config.database), document_models=[VideoModel, VideoTagModel, DirMetadataModel, MigrationTaskModel, SeriesModel])

    yield
    await SeriesModel.delete_all()
    await VideoModel.delete_all()
    await VideoTagModel.delete_all()
    await DirMetadataModel.delete_all()
    await MigrationTaskModel.delete_all()


# -----------------------------------------------------------------------
# ---------------------- Test data factory fixtures ----------------------
# -----------------------------------------------------------------------

@pytest_asyncio.fixture
def video_factory(init_db) -> Callable:
    """
    Factory fixture to create VideoModel documents in the test DB.

    Usage:
        video = await video_factory(name="my video")
        video = await video_factory(name="v2", tags=["action"], loved=True)
    """
    async def _create(**kwargs) -> VideoModel:
        defaults = {
            "category": "Test-category",
            "path": f"Test-category/Test-resource/{kwargs.get('name', 'default')}.mp4",
            "isDir": False,
            "lastModifyTime": 1700000000.0,
            "name": "Test Video",
            "size": 1024000.0,
            "tags": [],
            "duration": 120.0,
        }
        defaults.update(kwargs)
        video = VideoModel(**defaults)
        await video.insert()
        return video
    return _create


@pytest_asyncio.fixture
def series_factory(init_db) -> Callable:
    """
    Factory fixture to create a SeriesModel listing the given videos, in that order, and
    point each of them back at it.

    Usage:
        series = await series_factory("Show", a, b, c)
    """
    async def _create(name: str, *videos: VideoModel) -> SeriesModel:
        series = SeriesModel(name=name, videoIds=[v.id for v in videos])
        await series.insert()
        for video in videos:
            video.seriesId = series.id
            await video.save()
        return series
    return _create


@pytest_asyncio.fixture
def task_factory(init_db) -> Callable:
    """
    Factory fixture to create MigrationTaskModel documents in the test DB.

    Usage:
        task = await task_factory()
        task = await task_factory(status=TaskStatus.PROCESSING, file_size=100)
    """
    async def _create(**kwargs) -> MigrationTaskModel:
        now = time.time()
        defaults = {
            "source_path": "Test-category/Test-resource/movie_a.mp4",
            "source_category": "Test-category",
            "target_path": "Target-category/Target-resource/movie_a.mp4",
            "target_category": "Target-category",
            "file_name": "movie_a",
            "file_size": 100,
            "status": TaskStatus.PENDING,
            "created_at": now,
            "updated_at": now,
        }
        defaults.update(kwargs)
        task = MigrationTaskModel(**defaults)
        await task.insert()
        return task
    return _create


@pytest_asyncio.fixture
def tag_factory(init_db) -> Callable:
    """
    Factory fixture to create VideoTagModel documents in the test DB.

    Usage:
        tag = await tag_factory(name="action", tag_count=5)
    """
    async def _create(**kwargs) -> VideoTagModel:
        defaults = {
            "name": "test-tag",
            "tag_count": 1,
        }
        defaults.update(kwargs)
        tag = VideoTagModel(**defaults)
        await tag.insert()
        return tag
    return _create
