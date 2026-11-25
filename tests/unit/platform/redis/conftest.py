import pytest
import pytest_asyncio

from src.config import RedisConfig
from src.platform.redis.redis_cache import RedisCache
from src.platform.redis.redis_service import RedisService
from tests.cache_helpers import CapturedWarnings

# Nothing listens on port 1, so every call fails fast with a refused connection.
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"


@pytest_asyncio.fixture
async def unreachable_redis_cache():
    service = RedisService(RedisConfig(url=UNREACHABLE_REDIS_URL, socket_timeout=0.5))
    yield RedisCache(service)
    await service.aclose()


@pytest.fixture
def captured_warnings():
    with CapturedWarnings() as captured:
        yield captured
