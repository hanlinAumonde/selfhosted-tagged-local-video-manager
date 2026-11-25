"""Capture the warnings a degraded Redis call logs."""

from loguru import logger


class CapturedWarnings:
    """Collects loguru WARNING-or-above messages while active."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self._sink_id: int | None = None

    def __enter__(self) -> "CapturedWarnings":
        self._sink_id = logger.add(
            lambda message: self.messages.append(message.record["message"]),
            level="WARNING",
        )
        return self

    def __exit__(self, *exc) -> None:
        logger.remove(self._sink_id)
