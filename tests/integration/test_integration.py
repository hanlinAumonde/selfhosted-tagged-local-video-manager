"""Integration tests — end-to-end GraphQL operations against a real database."""

import pytest
from src.features.catalog.video import VideoModel
from src.features.catalog.video_tag import VideoTagModel
from tests.integration.graphql_documents import *
from tests.integration.helpers import *

# -----------------------------------------------------------------------
# Test: Browse directory discovers files and inserts into DB
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestBrowseAndDiscover:

    async def test_browse_root_shows_categories(self, execute_gql, init_db):
        result = await execute_gql(BROWSE_DIRECTORY, {"input": make_browse_input(None)})
        assert_no_errors(result)
        nodes = result.data["browseDirectory"]
        assert len(nodes) == 1
        assert nodes[0]["node"]["name"] == "Test-category"
        assert nodes[0]["node"]["isDir"] is True

    async def test_browse_category_shows_pseudo_names(self, execute_gql, init_db):
        result = await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category")},
        )
        assert_no_errors(result)
        nodes = result.data["browseDirectory"]
        names = [n["node"]["name"] for n in nodes]
        assert "Test-resource" in names

    async def test_browse_pseudo_root_discovers_videos(self, execute_gql, init_db):
        result = await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        assert_no_errors(result)
        nodes = result.data["browseDirectory"]
        names = [n["node"]["name"] for n in nodes]
        assert "alpha" in names
        assert "beta" in names
        dirs = [n for n in nodes if n["node"]["isDir"]]
        dir_names = [d["node"]["name"] for d in dirs]
        assert "drama" in dir_names

    async def test_browse_inserts_video_models_into_db(self, execute_gql, init_db):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        count = await VideoModel.find_all().count()
        assert count >= 2

    async def test_browse_subdirectory(self, execute_gql, init_db):
        result = await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource/drama")},
        )
        assert_no_errors(result)
        nodes = result.data["browseDirectory"]
        names = [n["node"]["name"] for n in nodes]
        assert "charlie" in names
        assert "delta" in names

    async def test_rebrowse_does_not_duplicate(self, execute_gql, init_db):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        videos = await VideoModel.find({"isDir": False}).to_list()
        paths = [v.path for v in videos]
        assert len(paths) == len(set(paths))


# -----------------------------------------------------------------------
# Test: Browse -> Search flow
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestBrowseAndSearch:

    async def test_search_finds_browsed_videos(self, execute_gql, init_db):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        result = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input()},
        )
        assert_no_errors(result)
        videos = result.data["SearchVideos"]["videos"]
        assert len(videos) >= 2
        names = [v["name"] for v in videos]
        assert "alpha" in names
        assert "beta" in names

    async def test_search_by_title_keyword(self, execute_gql, init_db):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        result = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input(titleKeyword={"keyWord": "alpha"})},
        )
        assert_no_errors(result)
        videos = result.data["SearchVideos"]["videos"]
        assert len(videos) == 1
        assert videos[0]["name"] == "alpha"

    async def test_search_pagination(self, execute_gql, init_db):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource/drama")},
        )
        result = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input()},
        )
        assert_no_errors(result)
        pagination = result.data["SearchVideos"]["pagination"]
        assert pagination["totalCount"] == 4
        assert pagination["currentPageNumber"] == 1


# -----------------------------------------------------------------------
# Test: Update metadata workflow
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestUpdateMetadata:

    async def _browse_and_get_video_id(self, execute_gql, name="alpha"):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        result = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input(titleKeyword={"keyWord": name})},
        )
        return result.data["SearchVideos"]["videos"][0]["id"]

    async def test_update_name_and_author(self, execute_gql, init_db):
        vid = await self._browse_and_get_video_id(execute_gql)
        result = await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": vid,
            "name": "Alpha Renamed",
            "author": "TestAuthor",
            "tags": [],
        }})
        assert_no_errors(result)
        data = result.data["updateVideoMetadata"]
        assert data["success"] is True
        assert data["video"]["name"] == "Alpha Renamed"
        assert data["video"]["author"] == "TestAuthor"

    async def test_update_tags_creates_tag_records(self, execute_gql, init_db):
        vid = await self._browse_and_get_video_id(execute_gql)
        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": vid,
            "tags": ["action", "drama"],
        }})
        tag_action = await VideoTagModel.find_one({"name": "action"})
        tag_drama = await VideoTagModel.find_one({"name": "drama"})
        assert tag_action is not None
        assert tag_action.tag_count == 1
        assert tag_drama is not None
        assert tag_drama.tag_count == 1

    async def test_update_loved(self, execute_gql, init_db):
        vid = await self._browse_and_get_video_id(execute_gql)
        result = await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": vid,
            "loved": True,
            "tags": [],
        }})
        assert_no_errors(result)
        assert result.data["updateVideoMetadata"]["video"]["loved"] is True

    async def test_update_persists_and_is_searchable(self, execute_gql, init_db):
        vid = await self._browse_and_get_video_id(execute_gql)
        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": vid,
            "author": "UniqueAuthor123",
            "tags": [],
        }})
        result = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input(author={"keyWord": "UniqueAuthor123"})},
        )
        assert_no_errors(result)
        assert len(result.data["SearchVideos"]["videos"]) == 1


# -----------------------------------------------------------------------
# Test: View tracking
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestViewTracking:

    async def test_record_view_increments_count(self, execute_gql, init_db, video_factory):
        video = await video_factory(name="viewed_video")
        vid = str(video.id)

        result = await execute_gql(RECORD_VIDEO_VIEW, {"videoId": vid})
        assert_no_errors(result)
        assert result.data["recordVideoView"]["video"]["viewCount"] == 1

        result = await execute_gql(RECORD_VIDEO_VIEW, {"videoId": vid})
        assert_no_errors(result)
        assert result.data["recordVideoView"]["video"]["viewCount"] == 2

    async def test_record_view_updates_last_view_time(self, execute_gql, init_db, video_factory):
        video = await video_factory(name="timed_video")
        vid = str(video.id)
        result = await execute_gql(RECORD_VIDEO_VIEW, {"videoId": vid})
        assert_no_errors(result)
        assert result.data["recordVideoView"]["video"]["lastViewTime"] > 0


# -----------------------------------------------------------------------
# Test: Tag lifecycle
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestTagLifecycle:

    async def test_tag_count_increments_and_decrements(self, execute_gql, init_db, video_factory):
        v1 = await video_factory(name="v1")
        v2 = await video_factory(name="v2")

        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": str(v1.id), "tags": ["sci-fi"],
        }})
        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": str(v2.id), "tags": ["sci-fi", "thriller"],
        }})

        tag = await VideoTagModel.find_one({"name": "sci-fi"})
        assert tag.tag_count == 2

        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": str(v1.id), "tags": [],
        }})
        tag = await VideoTagModel.find_one({"name": "sci-fi"})
        assert tag.tag_count == 1

    async def test_get_top_tags(self, execute_gql, init_db, video_factory):
        v1 = await video_factory(name="t1")
        v2 = await video_factory(name="t2")
        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": str(v1.id), "tags": ["popular", "rare"],
        }})
        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": str(v2.id), "tags": ["popular"],
        }})

        result = await execute_gql(GET_TOP_TAGS)
        assert_no_errors(result)
        tags = result.data["getTopTags"]
        popular = next(t for t in tags if t["name"] == "popular")
        assert popular["count"] == 2

    async def test_tag_suggestions(self, execute_gql, init_db, video_factory):
        v = await video_factory(name="suggest_v")
        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": str(v.id), "tags": ["animation", "adventure"],
        }})
        result = await execute_gql(GET_SUGGESTIONS, {"input": {
            "keyword": {"keyWord": "ani"},
            "suggestionType": "Tag",
        }})
        assert_no_errors(result)
        assert "animation" in result.data["getSuggestions"]


# -----------------------------------------------------------------------
# Test: Series management
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestSeriesManagement:

    async def test_assign_series_and_query(self, execute_gql, init_db, video_factory):
        v1 = await video_factory(name="ep1")
        v2 = await video_factory(name="ep2")
        vid1, vid2 = str(v1.id), str(v2.id)

        # Step 1: assign vid1 to series (only current video in orders)
        r1 = await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": vid1,
            "tags": [],
            "series": {
                "name": "MySeries",
                "clear": False,
                "orders": [{"videoId": vid1, "order": 1}],
            },
        }})
        assert_no_errors(r1)

        # Step 2: assign vid2 to series (vid1 already belongs, so valid)
        r2 = await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": vid2,
            "tags": [],
            "series": {
                "name": "MySeries",
                "clear": False,
                "orders": [
                    {"videoId": vid1, "order": 1},
                    {"videoId": vid2, "order": 2},
                ],
            },
        }})
        assert_no_errors(r2)

        result = await execute_gql(GET_SERIES_VIDEOS, {"name": "MySeries"})
        assert_no_errors(result)
        videos = result.data["getSeriesVideos"]
        assert len(videos) == 2
        assert videos[0]["seriesOrder"] == 1
        assert videos[1]["seriesOrder"] == 2

    async def test_search_series_by_prefix(self, execute_gql, init_db, video_factory):
        v = await video_factory(name="ser_v", seriesName="DragonBall")
        result = await execute_gql(SEARCH_SERIES_BY_PREFIX, {
            "prefix": "Dragon",
            "limit": 5,
        })
        assert_no_errors(result)
        assert "DragonBall" in result.data["searchSeriesByPrefix"]

    async def test_clear_series(self, execute_gql, init_db, video_factory):
        v = await video_factory(name="clear_v", seriesName="OldSeries", seriesOrder=1)
        vid = str(v.id)
        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": vid,
            "tags": [],
            "series": {"clear": True},
        }})
        result = await execute_gql(GET_VIDEO_BY_ID, {"videoId": vid})
        assert_no_errors(result)
        assert result.data["getVideoById"]["seriesName"] is None
        assert result.data["getVideoById"]["seriesOrder"] is None


# -----------------------------------------------------------------------
# Test: Delete workflow
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestDeleteWorkflow:

    async def test_delete_removes_from_db_and_filesystem(
        self, execute_gql, init_db, integration_resource_dir
    ):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        result = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input(titleKeyword={"keyWord": "alpha"})},
        )
        vid = result.data["SearchVideos"]["videos"][0]["id"]

        delete_result = await execute_gql(DELETE_VIDEO, {"videoId": vid})
        assert_no_errors(delete_result)
        assert delete_result.data["deleteVideo"]["success"] is True

        db_video = await VideoModel.find_one({"_id": vid})
        assert db_video is None

        assert not (integration_resource_dir / "alpha.mp4").exists()

    async def test_delete_decrements_tag_counts(
        self, execute_gql, init_db, integration_resource_dir
    ):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        result = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input(titleKeyword={"keyWord": "beta"})},
        )
        vid = result.data["SearchVideos"]["videos"][0]["id"]

        await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": vid, "tags": ["to-remove"],
        }})
        tag = await VideoTagModel.find_one({"name": "to-remove"})
        assert tag.tag_count == 1

        await execute_gql(DELETE_VIDEO, {"videoId": vid})
        tag = await VideoTagModel.find_one({"name": "to-remove"})
        assert tag is None or tag.tag_count == 0


# -----------------------------------------------------------------------
# Test: Directory metadata
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestDirectoryMetadata:

    async def test_metadata_calculated_after_browse(self, execute_gql, init_db):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        result = await execute_gql(GET_DIRECTORY_METADATA, {
            "input": make_browse_input("Test-category/Test-resource", skip_cache=True),
        })
        assert_no_errors(result)
        meta = result.data["getDirectoryMetadata"]
        assert meta["totalSize"] > 0
        assert meta["lastModifiedTime"] > 0

    async def test_metadata_includes_subdirectory_sizes(self, execute_gql, init_db):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource/drama")},
        )
        result = await execute_gql(GET_DIRECTORY_METADATA, {
            "input": make_browse_input("Test-category/Test-resource", skip_cache=True),
        })
        assert_no_errors(result)
        total_size = result.data["getDirectoryMetadata"]["totalSize"]
        assert total_size >= 10000

    async def test_root_level_returns_zero(self, execute_gql, init_db):
        result = await execute_gql(GET_DIRECTORY_METADATA, {
            "input": make_browse_input(None),
        })
        assert_no_errors(result)
        meta = result.data["getDirectoryMetadata"]
        assert meta["totalSize"] == 0.0
        assert meta["lastModifiedTime"] == 0.0


# -----------------------------------------------------------------------
# Test: Batch operations
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestBatchOperations:

    async def test_batch_update_by_ids(self, execute_gql, subscribe_gql, init_db, video_factory):
        v1 = await video_factory(name="batch1")
        v2 = await video_factory(name="batch2")
        vid1, vid2 = str(v1.id), str(v2.id)

        events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": {
            "videoIds": [vid1, vid2],
            "relativePath": {
                "relativePath": "Test-category/Test-resource",
                "skipCache": False,
                "recursiveCalculation": True,
            },
            "tagsOperation": {"addTags": ["batch-tag"], "removeTags": []},
            "author": "BatchAuthor",
        }})

        last_event = events[-1]
        assert last_event.data["batchUpdateSubscription"]["result"]["resultType"] == "Success"

        updated_v1 = await VideoModel.get(v1.id)
        assert "batch-tag" in updated_v1.tags
        assert updated_v1.author == "BatchAuthor"

    async def test_batch_delete_by_ids(
        self, execute_gql, subscribe_gql, init_db, integration_resource_dir
    ):
        await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        search = await execute_gql(
            SEARCH_VIDEOS, {"input": make_search_input()}
        )
        video_ids = [v["id"] for v in search.data["SearchVideos"]["videos"]]
        assert len(video_ids) >= 2

        target_id = video_ids[0]

        events = await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": {
            "videoIds": [target_id],
            "relativePath": {
                "relativePath": "Test-category/Test-resource",
                "skipCache": False,
                "recursiveCalculation": True,
            },
        }})

        last_event = events[-1]
        assert last_event.data["batchDeleteSubscription"]["result"]["resultType"] == "Success"

        deleted = await VideoModel.get(target_id)
        assert deleted is None

    async def test_batch_update_series_operation(
        self, execute_gql, subscribe_gql, init_db, video_factory
    ):
        v1 = await video_factory(name="ser_batch1")
        v2 = await video_factory(name="ser_batch2")
        vid1, vid2 = str(v1.id), str(v2.id)

        events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": {
            "videoIds": [vid1, vid2],
            "relativePath": {
                "relativePath": "Test-category/Test-resource",
                "skipCache": False,
                "recursiveCalculation": True,
            },
            "tagsOperation": {"addTags": [], "removeTags": []},
            "seriesOperation": {
                "name": "BatchSeries",
                "clear": False,
                "orders": [
                    {"videoId": vid1, "order": 1},
                    {"videoId": vid2, "order": 2},
                ],
            },
        }})

        last_event = events[-1]
        assert last_event.data["batchUpdateSubscription"]["result"]["resultType"] == "Success"

        updated_v1 = await VideoModel.get(v1.id)
        updated_v2 = await VideoModel.get(v2.id)
        assert updated_v1.seriesName == "BatchSeries"
        assert updated_v1.seriesOrder == 1
        assert updated_v2.seriesName == "BatchSeries"
        assert updated_v2.seriesOrder == 2


# -----------------------------------------------------------------------
# Test: Full user journey (browse -> update -> search -> delete)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
class TestFullUserJourney:

    async def test_complete_lifecycle(self, execute_gql, subscribe_gql, init_db, integration_resource_dir):
        """Simulate a complete user session: browse, update, search, view, delete."""

        # 1. Browse to discover videos
        browse_result = await execute_gql(
            BROWSE_DIRECTORY,
            {"input": make_browse_input("Test-category/Test-resource")},
        )
        assert_no_errors(browse_result)
        nodes = browse_result.data["browseDirectory"]
        video_nodes = [n for n in nodes if not n["node"]["isDir"]]
        assert len(video_nodes) >= 2

        # 2. Search all videos
        search_result = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input()},
        )
        assert_no_errors(search_result)
        all_videos = search_result.data["SearchVideos"]["videos"]
        vid_alpha = next(v["id"] for v in all_videos if v["name"] == "alpha")
        vid_beta = next(v["id"] for v in all_videos if v["name"] == "beta")

        # 3. Update alpha: add tags, set author, mark as loved
        update_result = await execute_gql(UPDATE_VIDEO_METADATA, {"input": {
            "videoId": vid_alpha,
            "name": "Alpha Prime",
            "author": "Director X",
            "loved": True,
            "tags": ["action", "sci-fi"],
        }})
        assert_no_errors(update_result)
        assert update_result.data["updateVideoMetadata"]["success"] is True

        # 4. Verify tags were created
        tag = await VideoTagModel.find_one({"name": "action"})
        assert tag is not None and tag.tag_count == 1

        # 5. Record views
        await execute_gql(RECORD_VIDEO_VIEW, {"videoId": vid_alpha})
        await execute_gql(RECORD_VIDEO_VIEW, {"videoId": vid_alpha})
        view_result = await execute_gql(GET_VIDEO_BY_ID, {"videoId": vid_alpha})
        assert_no_errors(view_result)
        assert view_result.data["getVideoById"]["viewCount"] == 2

        # 6. Search by author
        author_search = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input(author={"keyWord": "Director X"})},
        )
        assert_no_errors(author_search)
        assert len(author_search.data["SearchVideos"]["videos"]) == 1
        assert author_search.data["SearchVideos"]["videos"][0]["name"] == "Alpha Prime"

        # 7. Search by tag
        tag_search = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input(tags=["sci-fi"])},
        )
        assert_no_errors(tag_search)
        assert len(tag_search.data["SearchVideos"]["videos"]) == 1

        # 8. Delete alpha
        delete_result = await execute_gql(DELETE_VIDEO, {"videoId": vid_alpha})
        assert_no_errors(delete_result)
        assert delete_result.data["deleteVideo"]["success"] is True

        # 9. Verify alpha is gone from DB
        alpha_gone = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input(titleKeyword={"keyWord": "Alpha Prime"})},
        )
        assert alpha_gone.data["SearchVideos"]["pagination"]["totalCount"] == 0

        # 10. Verify alpha file deleted from filesystem
        assert not (integration_resource_dir / "alpha.mp4").exists()

        # 11. Verify tag counts decremented
        tag_after = await VideoTagModel.find_one({"name": "action"})
        assert tag_after is None or tag_after.tag_count == 0

        # 12. Beta still searchable
        beta_search = await execute_gql(
            SEARCH_VIDEOS,
            {"input": make_search_input(titleKeyword={"keyWord": "beta"})},
        )
        assert_no_errors(beta_search)
        assert len(beta_search.data["SearchVideos"]["videos"]) == 1