from src.config import Settings
from src.platform.storage.base_resource_handler import BaseResourceHandler, HandlerBuildSpec
from src.platform.storage.local_fs.local_fs_handler import LocalFSResourceHandler
from src.platform.storage.s3.s3_handler import S3ResourceHandler

_HANDLER_TYPES: dict[str, type[BaseResourceHandler]] = {
    LocalFSResourceHandler.storage_type: LocalFSResourceHandler,
    S3ResourceHandler.storage_type: S3ResourceHandler,
}


class ResourceHandlerService:
    """Dispatcher that selects the correct resource handler based on category."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._handlers: dict[str, BaseResourceHandler] = {}

        for category, pseudo_paths in settings.resource_paths.items():
            self._handlers[category] = self._create_handler(
                category, pseudo_paths, settings
            )

    @staticmethod
    def _create_handler(category: str,
                        pseudo_paths: dict[str, str],
                        settings: Settings) -> BaseResourceHandler:
        """
        Build the resource handler a category declares in its configuration.

        Reads the declared type, looks up the class serving it, and hands that class
        the same envelope every handler is built from.

        :param category: The category of the resource handler to create.
        :type category: str
        :param pseudo_paths: The mapping of pseudo paths for the category.
        :type pseudo_paths: dict[str, str]
        :param settings: The application settings containing handler configurations.
        :type settings: Settings
        :return: An instance of a resource handler for the specified category.
        :rtype: BaseResourceHandler
        :raises ValueError: If the declared type has no registered handler.
        """
        config = settings.get_handler_config(category)
        handler_cls = _HANDLER_TYPES.get(config.type)
        if handler_cls is None:
            known = ", ".join(sorted(_HANDLER_TYPES))
            raise ValueError(
                f"No handler for storage type '{config.type}'. Known types: {known}"
            )
        return handler_cls.from_config(
            HandlerBuildSpec(
                category=category,
                pseudo_paths=pseudo_paths,
                config=config,
                settings=settings,
            )
        )

    def get_handler(self, category: str) -> BaseResourceHandler:
        """
        Get the resource handler for the specified category.

        :param category: The category for which to retrieve the resource handler.
        :type category: str
        :return: The resource handler instance for the specified category.
        :rtype: BaseResourceHandler
        :raises ValueError: If no resource handler is found for the specified category.
        """
        handler = self._handlers.get(category)
        if handler is None:
            raise ValueError(f"No resource handler for category '{category}'")
        return handler

    def get_all_categories(self) -> list[str]:
        """Get a list of all categories that have resource handlers."""
        return list(self._handlers.keys())

    def get_pseudo_names(self, category: str) -> list[str]:
        """
        Get a list of all pseudo names for the specified category.

        :param category: The category for which to retrieve pseudo names.
        :type category: str
        :return: A list of pseudo names for the specified category.
        :rtype: list[str]
        :raises ValueError: If the category is not found in the configuration.
        """
        if category not in self._settings.resource_paths:
            raise ValueError(f"Category '{category}' not found in config")
        return list(self._settings.resource_paths[category].keys())
