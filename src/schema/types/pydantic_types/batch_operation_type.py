from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from src.config import get_settings
from src.features.browsing.directory_deletion import DirectoryDeletionStrategy
from src.schema.types.pydantic_types.fileBrowe_type import RelativePathInputModel

class SeriesOrderEntryInputModel(BaseModel):
    videoId: str
    order: int


class SeriesOperationInputModel(BaseModel):
    name: Optional[str] = None
    clear: bool = False
    orders: list[SeriesOrderEntryInputModel] = Field(default_factory=list)

    @field_validator("name", mode="after")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        settings = get_settings()
        max_length = settings.validation.series_name_max_length
        if len(v) > max_length:
            raise ValueError(f"Series name too long (max {max_length})")
        return v


class TagsOperationMappingInputModel(BaseModel):
    addTags: list[str] = Field(default_factory=list)
    removeTags: list[str] = Field(default_factory=list)

    @field_validator("addTags", "removeTags", mode="after")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        settings = get_settings()
        validation = settings.validation

        if len(v) > validation.max_tags_count:
            raise ValueError(f"Too many tags (max {validation.max_tags_count})")

        for tag in v:
            if len(tag) > validation.tag_max_length:
                raise ValueError(f"Tag '{tag}' too long (max {validation.tag_max_length})")

        return v

    @model_validator(mode="after")
    def reject_tags_named_in_both_directions(self) -> "TagsOperationMappingInputModel":
        """
        A tag in both lists says nothing about what the caller wants.

        Picking a winner would let them believe a tag was added when it was taken away,
        or the reverse, with nothing in the result to tell them apart.
        """
        overlap = sorted(set(self.addTags) & set(self.removeTags))
        if overlap:
            raise ValueError(
                f"Tags cannot be both added and removed: {', '.join(overlap)}"
            )
        return self


class BatchOperationInputModel(BaseModel):
    tagsOperation: Optional[TagsOperationMappingInputModel] = None
    author: Optional[str] = None

    @field_validator("author", mode="after")
    @classmethod
    def validate_author(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        settings = get_settings()
        max_length = settings.validation.author_max_length
        if len(v) > max_length:
            raise ValueError(f"Author too long (max {max_length})")
        return v
    
class VideosBatchOperationInputModel(BatchOperationInputModel):
    videoIds: list[str]
    relativePath: RelativePathInputModel
    seriesOperation: Optional[SeriesOperationInputModel] = None

    #: Only meaningful when deleting by directory: what becomes of the folder itself.
    directoryDeletion: Optional[DirectoryDeletionStrategy] = None