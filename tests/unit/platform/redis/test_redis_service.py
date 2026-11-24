"""RedisService: the one owner of a process's Redis connection and key names.

Runs against the real Redis testcontainer.
"""

import time

import pytest

from src.config import RedisConfig
from src.platform.redis.redis_service import REDIS_UNAVAILABLE, RedisService
from tests.unit.platform.redis.conftest import UNREACHABLE_REDIS_URL

pytestmark = pytest.mark.unit


class TestKeys:
    def test_key_joins_the_prefix_and_every_part_with_colons(self):
        # Given a RedisService whose key_prefix is "pfx"
        service = RedisService(RedisConfig(key_prefix="pfx"))

        # When key("task", "t1", "progress") is asked for
        # Then the key is "pfx:task:t1:progress"
        assert service.key("task", "t1", "progress") == "pfx:task:t1:progress"


class TestFailFast:
    async def test_a_call_to_an_unreachable_redis_fails_within_one_socket_timeout(self):
        # Given a RedisService pointed at an address where no Redis is listening,
        #   with socket_timeout 0.5
        service = RedisService(RedisConfig(url=UNREACHABLE_REDIS_URL, socket_timeout=0.5))
        try:
            # When a GET is sent through its client
            started = time.monotonic()
            # Then a Redis-unavailable error is raised
            with pytest.raises(REDIS_UNAVAILABLE):
                await service.client.get("k")
            # And it is raised within 2 seconds, so a degraded cache read costs one timeout
            #   and not a series of retries
            assert time.monotonic() - started < 2
        finally:
            await service.aclose()
