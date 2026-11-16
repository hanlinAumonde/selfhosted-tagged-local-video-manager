from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FileInfo:
    """
    One file or directory as the storage reported it, with every field already read.

    Deliberately carries no IO method. The entries it replaces stat'ed lazily, so the
    real IO happened wherever the caller happened to look — on the event loop, even when
    the listing itself had been moved onto a thread.
    """

    name: str
    #: FS-format path: a filesystem path for local storage, an object key for S3.
    path: str
    is_dir: bool
    size: float = 0.0
    mtime: float = 0.0
