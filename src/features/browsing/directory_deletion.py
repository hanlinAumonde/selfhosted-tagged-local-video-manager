from enum import Enum


class DirectoryDeletionStrategy(str, Enum):
    #: The videos go, the folder stays listed even though it now holds nothing.
    KeepFolder = "KeepFolder"

    #: The folder stops being listed. It also leaves the storage when nothing else is
    #: inside it; otherwise it is left exactly where it is and only marked as deleted.
    DeleteFolder = "DeleteFolder"
