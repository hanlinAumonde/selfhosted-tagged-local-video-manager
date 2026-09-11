from pydantic import BaseModel, Field, ValidationInfo, field_validator
from src.config import get_settings
from src.schema.types.pydantic_types.search_type import SearchKeywordModel, validate_tag_list

#: Characters that would make a directory name address something other than one child of
#: the directory the request is about.
_NAME_SEPARATORS = ("/", "\\")


class RelativePathInputModel(BaseModel):
    skipCache: bool = False  # If True, bypass any caching and get the latest info from disk

    recursiveCalculation: bool = True  # If True, calculate metadata for all subdirectories recursively; if False, only calculate for the specified directory without going into subdirectories

    relativePath: str | None = None  # If None, browse the root directory that contains all category names

    parsedPath: tuple[str, str | None, str | None]  | None = None  # not provided by user

    @field_validator("parsedPath", mode="after")
    @classmethod
    def parse_relative_path(cls, v: tuple | None, info: ValidationInfo) -> tuple[str, str | None, str | None] | None:
        """
        validate and parse the relative path, set it to parsed_path
        valid format: 1. None (browse root - show categories)
                      2. <category> (show pseudo names under category)
                      3. <category>/<pseudo_name> (browse pseudo root)
                      4. <category>/<pseudo_name>/<sub_path> (browse sub directory)
        """
        relativePath: str | None = info.data['relativePath']

        # validate the format
        if relativePath is None:
            return None
        if relativePath.startswith("/") or relativePath.endswith("/"):
            raise ValueError("relativePath should not start or end with '/'")
        if ".." in relativePath.split("/"):
            raise ValueError("relativePath should not contain '..'")

        settings = get_settings()
        parts = relativePath.split("/", 2)

        # validate category
        category = parts[0]
        if category not in settings.resource_paths:
            raise ValueError(f"Category '{category}' not found in configured resource paths")

        if len(parts) == 1:
            # category level only
            return (category, None, None)

        # validate pseudo name
        pseudo_name = parts[1]
        if pseudo_name not in settings.resource_paths[category]:
            raise ValueError(f"Pseudo name '{pseudo_name}' not found under category '{category}'")

        if len(parts) == 2:
            return (category, pseudo_name, None)

        return (category, pseudo_name, "/" + parts[2])


class SearchInDirectoryInputModel(BaseModel):
    """
    A search over one directory and everything below it.

    The keywords reuse ``SearchKeywordModel`` so they are escaped and length-checked
    exactly as the search page's are — the backend runs both through the same regex.
    """

    path: RelativePathInputModel  # the directory the search starts from

    name: SearchKeywordModel = Field(default_factory=SearchKeywordModel)

    author: SearchKeywordModel = Field(default_factory=SearchKeywordModel)

    tags: list[str] = Field(default_factory=list)

    @field_validator("tags", mode="after")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        return validate_tag_list(v)


class CreateDirectoryInputModel(BaseModel):
    parentPath: RelativePathInputModel  # the directory the new folder goes into

    name: str  # one path segment, the new folder's name

    @field_validator("name", mode="after")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """
        Accept one usable path segment, and return it trimmed.

        The trimmed value is what gets written, so trimming here rather than downstream
        keeps the name the client is told about identical to the name on disk.
        """
        cleaned = (v or "").strip()
        if not cleaned:
            raise ValueError("name should not be blank")
        if any(separator in cleaned for separator in _NAME_SEPARATORS):
            raise ValueError("name should not contain a path separator")
        if cleaned in (".", ".."):
            raise ValueError("name should not be a relative path reference")

        max_length = get_settings().validation.name_max_length
        if len(cleaned) > max_length:
            raise ValueError(f"name should be at most {max_length} characters")
        return cleaned
