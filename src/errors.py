class VideoNotFoundError(Exception):
    def __init__(self, video_id: str):
        self.video_id = video_id
        super().__init__(f"Video with ID {video_id} not found")


class VideoFileNotFoundError(Exception):
    """The video record exists but its file is no longer in storage."""

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Video file not found: {path}")


class InvalidRangeError(Exception):
    """A Range request that starts or ends past the end of the file."""

    def __init__(self, file_size: int):
        # A 416 must say how large the file is, so the client can ask again.
        self.file_size = file_size
        super().__init__(f"Requested range is outside a file of {file_size} bytes")


class InvalidPathError(Exception):
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Invalid path: {path}")


class FileBrowseError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"File browse error: {message}")

class DatabaseOperationError(Exception):
    def __init__(self, operation: str, details: str):
        self.operation = operation
        self.details = details
        super().__init__(f"Database operation '{operation}' failed: {details}")

class InputValidationError(Exception):
    def __init__(self, field: str, issue: str):
        self.field = field
        self.issue = issue
        super().__init__(f"Input validation error on field '{field}': {issue}")

class _MigrationCancelled(Exception):
    pass