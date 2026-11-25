from fastapi import status

from src.errors import InputValidationError, InvalidRangeError, VideoFileNotFoundError, VideoNotFoundError

#: The status each error in src/errors.py is answered with when it escapes a REST route.
ERROR_STATUS_CODES: dict[type[Exception], int] = {
    VideoNotFoundError: status.HTTP_404_NOT_FOUND,
    VideoFileNotFoundError: status.HTTP_404_NOT_FOUND,
    InputValidationError: status.HTTP_400_BAD_REQUEST,
    InvalidRangeError: status.HTTP_416_RANGE_NOT_SATISFIABLE,
}

#: Detail of a 500, which must not reveal the error that caused it.
INTERNAL_ERROR_DETAIL = "Internal server error"

#: A video's thumbnail key is derived from its id, so a cached image never goes stale.
THUMBNAIL_CACHE_CONTROL = "public, max-age=3600"
