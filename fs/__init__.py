"""fs - A simple, versioned vault for agents."""

from fs.overlay import FolderProvider, OverlayFS
from fs.vault import Commit, FileMeta, FileVersion, Vault

__version__ = "0.1.0"
__all__ = ["Vault", "FileVersion", "FileMeta", "Commit", "OverlayFS", "FolderProvider"]
