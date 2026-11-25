#: Default of the published pageSize argument. A literal rather than a setting: strawberry
#: builds the schema, defaults included, when its modules are imported, before any
#: configuration is loaded.
MIGRATION_PAGE_SIZE_DEFAULT = 20

#: Regex metacharacters that need escaping for MongoDB $regex.
REGEX_SPECIAL_CHARS = r'\.*+?[](){}|^$'
