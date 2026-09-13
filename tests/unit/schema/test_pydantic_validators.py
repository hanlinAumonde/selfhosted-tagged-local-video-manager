"""Unit tests for Pydantic input-model validators."""

import pytest

from src.schema.types.pydantic_types.batch_operation_type import (
    BatchOperationInputModel,
    SeriesOperationInputModel,
    TagsOperationMappingInputModel,
)
from src.schema.types.pydantic_types.fileBrowe_type import RelativePathInputModel
from src.schema.types.pydantic_types.search_type import (
    VideoSearchInputModel,
    SearchKeywordModel,
)
from src.schema.types.pydantic_types.video_type import (
    SeriesFieldInputModel,
    UpdateVideoMetadataInputModel,
)

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------
# batch_operation_type.py
# -----------------------------------------------------------------------

class TestSeriesOperationInputModel:
    def test_series_name_too_long(self, test_settings):
        max_len = test_settings.validation.series_name_max_length
        with pytest.raises(ValueError, match="Series name too long"):
            SeriesOperationInputModel(name="x" * (max_len + 1), clear=False, orders=[])

    def test_series_name_none_passes(self):
        model = SeriesOperationInputModel(name=None, clear=True, orders=[])
        assert model.name is None


class TestTagsOperationMappingInputModel:
    def test_too_many_tags(self, test_settings):
        max_count = test_settings.validation.max_tags_count
        with pytest.raises(ValueError, match="Too many tags"):
            TagsOperationMappingInputModel(
                append=True, tags=[f"t{i}" for i in range(max_count + 1)]
            )

    def test_tag_too_long(self, test_settings):
        max_len = test_settings.validation.tag_max_length
        with pytest.raises(ValueError, match="too long"):
            TagsOperationMappingInputModel(append=True, tags=["x" * (max_len + 1)])


class TestBatchOperationInputModel:
    def test_author_too_long(self, test_settings):
        max_len = test_settings.validation.author_max_length
        with pytest.raises(ValueError, match="Author too long"):
            BatchOperationInputModel(
                tagsOperation=None, author="x" * (max_len + 1)
            )

    def test_author_none_passes(self):
        model = BatchOperationInputModel(tagsOperation=None, author=None)
        assert model.author is None


# -----------------------------------------------------------------------
# fileBrowe_type.py
# -----------------------------------------------------------------------

class TestRelativePathInputModel:
    def test_path_starts_with_slash(self):
        with pytest.raises(ValueError, match="should not start or end with"):
            RelativePathInputModel(relativePath="/bad/path", parsedPath=None)

    def test_path_ends_with_slash(self):
        with pytest.raises(ValueError, match="should not start or end with"):
            RelativePathInputModel(relativePath="bad/path/", parsedPath=None)

    def test_path_contains_dotdot(self):
        with pytest.raises(ValueError, match="should not contain"):
            RelativePathInputModel(relativePath="Test-category/../etc", parsedPath=None)

    def test_pseudo_name_not_found(self):
        with pytest.raises(ValueError, match="Pseudo name"):
            RelativePathInputModel(relativePath="Test-category/nonexistent", parsedPath=None)

    def test_category_not_found(self):
        with pytest.raises(ValueError, match="Category"):
            RelativePathInputModel(relativePath="NoSuchCategory", parsedPath=None)


# -----------------------------------------------------------------------
# search_type.py
# -----------------------------------------------------------------------

class TestVideoSearchInputModel:
    def test_too_many_search_tags(self, test_settings):
        max_count = test_settings.validation.max_tags_count
        with pytest.raises(ValueError, match="Too many tags"):
            VideoSearchInputModel(
                titleKeyword=SearchKeywordModel(keyWord=None),
                author=SearchKeywordModel(keyWord=None),
                tags=[f"t{i}" for i in range(max_count + 1)],
                sortBy="Latest",
                fromPage="SearchPage",
            )

    def test_search_tag_too_long(self, test_settings):
        max_len = test_settings.validation.tag_max_length
        with pytest.raises(ValueError, match="too long"):
            VideoSearchInputModel(
                titleKeyword=SearchKeywordModel(keyWord=None),
                author=SearchKeywordModel(keyWord=None),
                tags=["x" * (max_len + 1)],
                sortBy="Latest",
                fromPage="SearchPage",
            )

    def test_page_number_out_of_range(self, test_settings):
        high = test_settings.validation.page_number_max
        with pytest.raises(ValueError, match="Page number must be between"):
            VideoSearchInputModel(
                titleKeyword=SearchKeywordModel(keyWord=None),
                author=SearchKeywordModel(keyWord=None),
                tags=[],
                sortBy="Latest",
                fromPage="SearchPage",
                currentPageNumber=high + 1,
            )

    def test_page_number_none_defaults_to_one(self):
        model = VideoSearchInputModel(
            titleKeyword=SearchKeywordModel(keyWord=None),
            author=SearchKeywordModel(keyWord=None),
            tags=[],
            sortBy="Latest",
            fromPage="SearchPage",
            currentPageNumber=None,
        )
        assert model.currentPageNumber == 1


# -----------------------------------------------------------------------
# video_type.py (Pydantic models)
# -----------------------------------------------------------------------

class TestSeriesFieldInputModel:
    def test_series_name_too_long(self, test_settings):
        max_len = test_settings.validation.series_name_max_length
        with pytest.raises(ValueError, match="Series name too long"):
            SeriesFieldInputModel(
                name="x" * (max_len + 1),
                clear=False,
                orders=[{"videoId": "abc", "order": 1}],
            )

    def test_invalid_combo_no_name_no_clear(self):
        with pytest.raises(ValueError, match="requires either clear=true"):
            SeriesFieldInputModel(name=None, clear=False, orders=[])


class TestUpdateVideoMetadataInputModel:
    def test_introduction_too_long(self, test_settings):
        max_len = test_settings.validation.introduction_max_length
        with pytest.raises(ValueError, match="Introduction too long"):
            UpdateVideoMetadataInputModel(
                videoId="abc", tags=[], introduction="x" * (max_len + 1)
            )

    def test_author_too_long(self, test_settings):
        max_len = test_settings.validation.author_max_length
        with pytest.raises(ValueError, match="Author too long"):
            UpdateVideoMetadataInputModel(
                videoId="abc", tags=[], author="x" * (max_len + 1)
            )

    def test_tag_too_long(self, test_settings):
        max_len = test_settings.validation.tag_max_length
        with pytest.raises(ValueError, match="too long"):
            UpdateVideoMetadataInputModel(
                videoId="abc", tags=["x" * (max_len + 1)]
            )
