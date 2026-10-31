import uuid

import pytest
import pytest_asyncio
from testcontainers.community.redis import RedisContainer

from src.platform.cache.redis_cache import RedisCache
from tests.cache_helpers import CapturedWarnings

# Nothing listens on port 1, so every call fails fast with a refused connection.
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"


@pytest.fixture
def prefix() -> str:
    # Unique per test: the container is shared across the session.
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def redis_cache(redis_url: str, prefix: str):
    cache = RedisCache(url=redis_url, socket_timeout=1.0, key_prefix=prefix)
    yield cache
    await cache.clear()
    await cache.close()


@pytest.fixture
def raw_redis(redis_container: RedisContainer):
    """A plain client for inspecting what actually landed in Redis."""
    client = redis_container.get_client(decode_responses=True)
    yield client
    client.close()


@pytest_asyncio.fixture
async def unreachable_redis_cache():
    cache = RedisCache(url=UNREACHABLE_REDIS_URL, socket_timeout=0.5, key_prefix="pfx")
    yield cache
    await cache.close()


@pytest.fixture
def captured_warnings():
    with CapturedWarnings() as captured:
        yield captured
