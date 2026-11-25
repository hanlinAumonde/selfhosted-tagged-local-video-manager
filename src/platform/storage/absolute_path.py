from src.config import Settings
from src.errors import FileBrowseError
from src.platform.storage.base_resource_handler import BaseResourceHandler
from src.platform.storage.resource_handler_service import ResourceHandlerService

class AbsolutePath:

    def __init__(self, abs_path: str | None, category: str | None = None, handler: BaseResourceHandler | None = None):
        self.abs_path = abs_path
        self.category = category
        self.handler = handler

    @classmethod
    def from_relative_path(
        cls, 
        parsedPath: tuple[str, str | None, str | None] | None,
        handlerService: ResourceHandlerService | None = None,
        settings: Settings | None = None) -> 'AbsolutePath':
        """
        Create AbsolutePath from parsed relative path tuple.
        Delegates path resolution to the handler for the given category.

        :param parsedPath: A tuple of (category, pseudo_name, sub_path) or None for root level.
        :type parsedPath: tuple[str, str | None, str | None] | None
        :param handlerService: Supplies the handler of the path's category.
        :type handlerService: ResourceHandlerService | None
        :param settings: Used to check the category and pseudo name are configured.
        :type settings: Settings | None
        :raises FileBrowseError: If the category or pseudo name is not configured.
        :return: An AbsolutePath instance representing the resolved absolute path.
        :rtype: AbsolutePath
        """
        if parsedPath is None:
            return cls(None, category=None, handler=None) 

        category, pseudo_name, sub_path = parsedPath

        if category not in settings.resource_paths:
            raise FileBrowseError(f"Category '{category}' not found in resource paths.")

        if pseudo_name is not None and pseudo_name not in settings.resource_paths[category]:
            raise FileBrowseError(f"Pseudo name '{pseudo_name}' not found under category '{category}'.")

        handler = handlerService.get_handler(category)
        abs_path = handler.resolve_path(category, pseudo_name, sub_path)
        return cls(abs_path, category=category, handler=handler)

    @classmethod
    def from_existing_path(cls, path: str, category: str, handler: BaseResourceHandler | None = None) -> 'AbsolutePath':
        """
        Create AbsolutePath from an existing path (e.g. from DB or os.scandir) with known category.

        :param path: The existing absolute path.
        :type path: str
        :param category: The category of the path.
        :type category: str
        :param handler: The handler of that category, needed by the format conversions.
        :type handler: BaseResourceHandler | None
        :return: An AbsolutePath instance representing the existing path.
        :rtype: AbsolutePath
        """
        return cls(path, category=category, handler=handler)

    def DB_format_path(self) -> str | None:
        """Convert the absolute path to the DB storage format using the handler's conversion method."""
        if self.abs_path is None:
            return None
        return self.handler.convert_to_DB_format_path(self.abs_path)

    def FS_format_path(self) -> str | None:
        """Convert the absolute path to the file system format using the handler's conversion method."""
        if self.abs_path is None:
            return None
        return self.handler.convert_to_FS_format_path(self.abs_path)

    def get_path(self) -> str | None:
        """Get the absolute path in the standard format using the handler's method."""
        if self.abs_path is None:
            return None
        return self.handler.get_path_standard_format(self.abs_path)

    def update_path(self, new_abs_path: str) -> None:
        """
        Update the absolute path to a new value.

        :param new_abs_path: The new path, in the same format the instance was built with.
        :type new_abs_path: str
        """
        self.abs_path = new_abs_path

    def is_root_level(self) -> bool:
        """Check if this path represents the root level."""
        return self.abs_path is None and self.category is None

    def is_category_level(self) -> bool:
        """Check if this path represents a category level."""
        return self.abs_path is not None and self.category is not None and self.abs_path == self.category
