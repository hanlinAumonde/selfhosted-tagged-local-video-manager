"""The HTTP status a REST client gets for each error a route lets escape.

Routes and the services behind them raise the types in ``src/errors.py``; the handlers
``src/app.py`` registers are the only place those types become status codes.
"""

import json
from contextlib import suppress
from dataclasses import dataclass

import pytest
from fastapi import FastAPI, status

from src.app import register_exception_handlers
from src.errors import (
    InputValidationError,
    InvalidRangeError,
    VideoFileNotFoundError,
    VideoNotFoundError,
)

pytestmark = pytest.mark.unit


@dataclass
class _Response:
    status_code: int
    headers: dict[str, str]
    text: str

    def json(self):
        return json.loads(self.text)


async def _call_route_raising(exc: Exception) -> _Response:
    """
    Call, over raw ASGI, an app whose only route raises ``exc``.

    Raw ASGI rather than starlette's TestClient, which needs an HTTP client package the
    project does not otherwise depend on.
    """
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise exc

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": "/boom", "raw_path": b"/boom",
        "root_path": "", "query_string": b"", "headers": [],
        "client": ("test", 0), "server": ("test", 80),
    }
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    # Starlette re-raises an unhandled error after its 500 handler has answered, so
    # the server can log it; the answer is what this test is about.
    with suppress(type(exc)):
        await app(scope, receive, send)

    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return _Response(
        status_code=start["status"],
        headers={k.decode().lower(): v.decode() for k, v in start["headers"]},
        text=body.decode(),
    )


async def test_video_not_found_becomes_404():
    """
    Given a route that raises VideoNotFoundError
    When a client calls it
    Then the response is 404 with the error message as its detail
    """
    exc = VideoNotFoundError("abc")

    response = await _call_route_raising(exc)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": str(exc)}


async def test_video_file_not_found_becomes_404():
    """
    Given a route that raises VideoFileNotFoundError
    When a client calls it
    Then the response is 404 with the error message as its detail
    """
    exc = VideoFileNotFoundError("Local/Res/v.mp4")

    response = await _call_route_raising(exc)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": str(exc)}


async def test_input_validation_error_becomes_400():
    """
    Given a route that raises InputValidationError
    When a client calls it
    Then the response is 400 with the error message as its detail
    """
    exc = InputValidationError(field="video_id", issue="must not be empty")

    response = await _call_route_raising(exc)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {"detail": str(exc)}


async def test_invalid_range_becomes_416_with_content_range():
    """
    Given a route that raises InvalidRangeError for a file of 1024 bytes
    When a client calls it
    Then the response is 416
    And its Content-Range header is "bytes */1024", as RFC 9110 asks of a 416
    """
    response = await _call_route_raising(InvalidRangeError(file_size=1024))

    assert response.status_code == status.HTTP_416_RANGE_NOT_SATISFIABLE
    assert response.headers["content-range"] == "bytes */1024"


async def test_unexpected_error_becomes_500_without_leaking_its_message():
    """
    Given a route that raises an exception not defined in src/errors.py
    When a client calls it
    Then the response is 500
    And the detail is a generic message, not the exception's own text
    """
    response = await _call_route_raising(RuntimeError("secret internals"))

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "secret internals" not in response.text
