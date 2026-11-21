from uuid import uuid4

from src import config
from src.config import Settings
from tests.integration.graphql_documents import (
    BROWSE_DIRECTORY,
    GET_TOP_TAGS,
    SEARCH_VIDEOS,
    UPDATE_VIDEO_METADATA,
)

#: The configured mount every journey starts from, and its one sub-directory.
RESOURCE_DIR = "Test-category/Test-resource"
DRAMA_DIR = f"{RESOURCE_DIR}/drama"


def assert_no_errors(result):
    assert result.errors is None or result.errors == [], (
        f"Expected no GraphQL errors, got: {result.errors}"
    )


def make_browse_input(relative_path=None, skip_cache=False, recursive=True):
    return {
        "relativePath": relative_path,
        "skipCache": skip_cache,
        "recursiveCalculation": recursive,
    }


def make_search_input(**overrides):
    base = {
        "titleKeyword": {"keyWord": None},
        "author": {"keyWord": None},
        "tags": [],
        "sortBy": "Latest",
        "fromPage": "SearchPage",
        "currentPageNumber": 1,
    }
    base.update(overrides)
    return base


def make_batch_input(video_ids, relative_path, **overrides):
    """A batch update/delete request; ``relative_path`` is the directory it was made from."""
    base = {
        "videoIds": list(video_ids),
        "relativePath": make_browse_input(relative_path),
        "tagsOperation": {"addTags": [], "removeTags": []},
    }
    base.update(overrides)
    return base


async def browse_nodes(execute_gql, relative_path: str) -> dict[str, dict]:
    """Browse a directory through GraphQL and return its rows keyed by name."""
    result = await execute_gql(BROWSE_DIRECTORY, {"input": make_browse_input(relative_path)})
    assert_no_errors(result)
    return {row["node"]["name"]: row["node"] for row in result.data["browseDirectory"]}


async def discover_videos(execute_gql, *relative_paths: str) -> dict[str, str]:
    """Browse each directory the way a user reaches its files; returns video name -> id."""
    ids: dict[str, str] = {}
    for path in relative_paths:
        ids.update(
            (name, node["id"])
            for name, node in (await browse_nodes(execute_gql, path)).items()
            if not node["isDir"]
        )
    return ids


async def searched_names(execute_gql, **search) -> tuple[list[str], int]:
    """Search through GraphQL; returns the sorted names on the first page and the total."""
    result = await execute_gql(SEARCH_VIDEOS, {"input": make_search_input(**search)})
    assert_no_errors(result)
    page = result.data["SearchVideos"]
    return sorted(v["name"] for v in page["videos"]), page["pagination"]["totalCount"]


async def update_video(execute_gql, video_id: str, **fields) -> dict:
    """Edit one video through GraphQL, the way its edit panel does."""
    result = await execute_gql(
        UPDATE_VIDEO_METADATA, {"input": {"videoId": video_id, "tags": [], **fields}}
    )
    assert_no_errors(result)
    return result.data["updateVideoMetadata"]["video"]


async def top_tags(execute_gql) -> dict[str, int]:
    result = await execute_gql(GET_TOP_TAGS)
    assert_no_errors(result)
    return {tag["name"]: tag["count"] for tag in result.data["getTopTags"]}


async def collect_stream(stream) -> list:
    """Every event a subscription stream still has to give, until it ends."""
    return [event async for event in stream]


def build_integration_settings(
    test_settings: Settings, resource_paths: dict, redis_url: str, monkeypatch
) -> Settings:
    """Settings pointing at the given resource directories and the test Redis, installed
    as the process-wide settings the way init_settings() would.

    The cache is Redis, as deployed: the worker refreshes directory metadata through its
    own cache client, and a per-process cache would leave the web side reading stale
    sizes. Every test gets its own key prefix, so cached entries and progress channels
    never leak from one test into the next."""
    payload = test_settings.model_dump()
    payload["resource_paths"] = resource_paths
    payload["tasks"]["redis_url"] = redis_url
    payload["cache_config"]["cache_type"] = "redis"
    payload["cache_config"]["redis"]["url"] = redis_url
    payload["cache_config"]["key_prefix"] = f"integration-{uuid4().hex[:12]}"
    settings = Settings.model_validate(payload)
    monkeypatch.setattr(config, "_settings", settings)
    return settings
