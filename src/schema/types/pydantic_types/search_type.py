import re
from typing import Optional
from pydantic import BaseModel, field_validator
from src.config import get_settings

# Regex metacharacters that need escaping for MongoDB $regex
REGEX_SPECIAL_CHARS = r'\.*+?[](){}|^$'

def escape_unescaped(text: str, special_chars: str) -> str:
    pattern = rf'(?<!\\)(?:\\\\)*([{re.escape(special_chars)}])'
    return re.sub(pattern, r'\\\1', text)

class SearchKeywordModel(BaseModel):
    keyWord: Optional[str] = None

    @field_validator("keyWord", mode="after")
    @classmethod
    def validate_and_escape_keyword(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        settings = get_settings()
        max_length = settings.validation.name_max_length
        if len(v) > max_length:
            raise ValueError(f"Keyword too long (max {max_length})")
        # Escape regex special characters
        return escape_unescaped(v, REGEX_SPECIAL_CHARS)


def validate_tag_list(v: list[str]) -> list[str]:
    """
    Check a list of tag filters against the configured limits.

    Shared rather than written per input model: every surface that filters by tag is
    filtering the same field, so a tag that is too long in one place must be too long in
    all of them.
    """
    validation = get_settings().validation

    if len(v) > validation.max_tags_count:
        raise ValueError(f"Too many tags (max {validation.max_tags_count})")

    for tag in v:
        if len(tag) > validation.tag_max_length:
            raise ValueError(f"Tag '{tag}' too long (max {validation.tag_max_length})")

    return v


class SuggestionInputModel(BaseModel):
    keyword: SearchKeywordModel
    suggestionType: str  


class VideoSearchInputModel(BaseModel):
    titleKeyword: SearchKeywordModel
    author: SearchKeywordModel
    tags: list[str]
    sortBy: str  
    fromPage: str  
    currentPageNumber: Optional[int] = 1

    @field_validator("tags", mode="after")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        return validate_tag_list(v)

    @field_validator("currentPageNumber", mode="after")
    @classmethod
    def validate_page_number(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return 1
        settings = get_settings()
        validation = settings.validation
        if v < validation.page_number_min or v > validation.page_number_max:
            raise ValueError(f"Page number must be between {validation.page_number_min} and {validation.page_number_max}")
        return v