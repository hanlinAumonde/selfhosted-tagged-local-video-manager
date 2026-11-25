from beanie import init_beanie
from pymongo import AsyncMongoClient
from src.features.catalog.video_model import VideoModel
from src.features.catalog.series_model import SeriesModel
from src.features.catalog.video_tag_model import VideoTagModel
from src.features.browsing.dir_metadata_model import DirMetadataModel
from src.features.migration.migration_batch_model import MigrationBatchModel
from src.features.migration.migration_task_model import MigrationTaskModel
from src.config import MongoConfig
from src.logger import get_logger

logger = get_logger("setup_mongo")

async def setup_mongo(mongo_config: MongoConfig):
    """
    Connect to MongoDB and register every document model with Beanie.

    :param mongo_config: The ``mongo`` section of the settings. Credentials, when set,
        authenticate against the application database itself.
    :type mongo_config: MongoConfig
    """
    #create an async MongoDB client
    mongo_uri = "mongodb://"
    mongo_host_port = f"{mongo_config.host}:{mongo_config.port}"
    if mongo_config.username and mongo_config.password:
        mongo_uri += f"{mongo_config.username}:{mongo_config.password}@" + mongo_host_port + f"/{mongo_config.database}?authSource={mongo_config.database}"
    else:
        mongo_uri += mongo_host_port
    
    client = AsyncMongoClient(mongo_uri)

    #initialize Beanie with the client and database name
    await init_beanie(
        database=client.get_database(mongo_config.database), 
        document_models=[
            VideoModel, 
            VideoTagModel, 
            DirMetadataModel, 
            MigrationTaskModel, 
            MigrationBatchModel, 
            SeriesModel
        ]
    )
    logger.info("MongoDB setup complete")