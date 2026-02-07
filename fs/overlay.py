"""Overlay filesystem that combines a Vault with read-only folder providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from fs.vault import Vault


class FolderProvider(ABC):
    """Abstract base class for read-only folder providers.

    Implementations supply the contents of a virtual folder
    that gets mounted at a path in the overlay filesystem.
    All paths are relative to the mount point (no leading slash).
    """

    @abstractmethod
    def list(self) -> list[str]:
        """List all file paths provided by this provider.

        Returns paths relative to the mount point, e.g. ["file.txt", "sub/file.txt"].
        """
        ...

    @abstractmethod
    def read(self, path: str) -> bytes:
        """Read a file by its path relative to the mount point.

        :raises FileNotFoundError: If the file does not exist.
        """
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if a path exists (file or directory) relative to the mount point."""
        ...

    @abstractmethod
    def is_dir(self, path: str) -> bool:
        """Check if a path is a directory relative to the mount point."""
        ...


class OverlayFS:
    """Wraps a Vault with read-only folder provider mounts.

    Implements the same interface as Vault so bin/ commands can use it
    transparently. Paths that fall under a mount point are handled by the
    corresponding FolderProvider; everything else is delegated to the Vault.
    """

    def __init__(self, vault: Vault, mounts: Optional[dict[str, FolderProvider]] = None):
        self._vault = vault
        self._mounts: dict[str, FolderProvider] = {}
        if mounts:
            for path, provider in mounts.items():
                self.mount(path, provider)

    def mount(self, path: str, provider: FolderProvider):
        """Register a folder provider at a mount point.

        :param path: Mount point path (e.g. "sys", "mnt/data"). Leading/trailing slashes stripped.
        :param provider: The folder provider to mount.
        """
        path = path.strip("/")
        if not path:
            raise ValueError("Cannot mount at root")
        self._mounts[path] = provider

    def _find_mount(self, filepath: str) -> Optional[tuple[str, str, FolderProvider]]:
        """Find the mount that owns a filepath.

        :returns: (mount_point, relative_path, provider) or None
        """
        filepath = filepath.strip("/")
        for mount_point, provider in self._mounts.items():
            if filepath == mount_point:
                return mount_point, "", provider
            if filepath.startswith(mount_point + "/"):
                rel = filepath[len(mount_point) + 1:]
                return mount_point, rel, provider
        return None

    def _is_mount_point(self, path: str) -> bool:
        path = path.strip("/")
        return path in self._mounts

    # --- Vault-compatible interface ---

    def list(self, sort_by_recent: bool = False) -> list[str]:
        files = self._vault.list(sort_by_recent=sort_by_recent)
        for mount_point, provider in self._mounts.items():
            for rel_path in provider.list():
                files.append(mount_point + "/" + rel_path.strip("/"))
        return files

    def list_with_metadata(self, sort_by_recent: bool = False):
        from fs.vault import FileMeta
        results = self._vault.list_with_metadata(sort_by_recent=sort_by_recent)
        for mount_point, provider in self._mounts.items():
            for rel_path in provider.list():
                results.append(FileMeta(
                    filepath=mount_point + "/" + rel_path.strip("/"),
                    timestamp=None,
                    author=None,
                    size=None,
                ))
        return results

    def read(self, filepath: str) -> bytes:
        filepath = filepath.strip("/")
        match = self._find_mount(filepath)
        if match:
            _, rel_path, provider = match
            if not rel_path:
                raise FileNotFoundError(f"'{filepath}' is a mount point (directory)")
            return provider.read(rel_path)
        return self._vault.read(filepath)

    def exists(self, path: str) -> bool:
        path = path.strip("/")
        if not path:
            return True
        # Check mounts
        if self._is_mount_point(path):
            return True
        match = self._find_mount(path)
        if match:
            _, rel_path, provider = match
            return provider.exists(rel_path)
        return self._vault.exists(path)

    def is_dir(self, path: str) -> bool:
        path = path.strip("/")
        if not path:
            return True
        # A mount point is always a directory
        if self._is_mount_point(path):
            return True
        match = self._find_mount(path)
        if match:
            _, rel_path, provider = match
            return provider.is_dir(rel_path)
        return self._vault.is_dir(path)

    def write(self, filepath: str, content: bytes, author: Optional[str] = None, mode: Optional[str] = None):
        filepath_clean = filepath.strip("/")
        if self._is_mount_point(filepath_clean) or self._find_mount(filepath_clean):
            raise PermissionError(f"Cannot write to read-only mount: {filepath}")
        self._vault.write(filepath, content, author=author, mode=mode)

    def delete(self, filepath: str):
        filepath_clean = filepath.strip("/")
        if self._is_mount_point(filepath_clean) or self._find_mount(filepath_clean):
            raise PermissionError(f"Cannot delete from read-only mount: {filepath}")
        self._vault.delete(filepath)

    def copy(self, src: str, dst: str):
        src_clean = src.strip("/")
        dst_clean = dst.strip("/")
        # Block writes into read-only mounts
        if self._is_mount_point(dst_clean) or self._find_mount(dst_clean):
            raise PermissionError(f"Cannot write to read-only mount: {dst}")
        # If source is in a mount, read from mount and write to vault
        match = self._find_mount(src_clean)
        if match:
            _, rel_path, provider = match
            if not rel_path:
                # Copying an entire mount point directory
                for rel in provider.list():
                    content = provider.read(rel)
                    self._vault.write(dst_clean + "/" + rel.strip("/"), content)
                return
            if provider.is_dir(rel_path):
                for rel in provider.list():
                    if rel.startswith(rel_path + "/") or rel == rel_path:
                        content = provider.read(rel)
                        sub = rel[len(rel_path):].strip("/")
                        self._vault.write(dst_clean + "/" + sub if sub else dst_clean, content)
                return
            content = provider.read(rel_path)
            self._vault.write(dst_clean, content)
            return
        self._vault.copy(src, dst)

    def move(self, src: str, dst: str):
        src_clean = src.strip("/")
        dst_clean = dst.strip("/")
        if self._is_mount_point(src_clean) or self._find_mount(src_clean):
            raise PermissionError(f"Cannot move from read-only mount: {src}")
        if self._is_mount_point(dst_clean) or self._find_mount(dst_clean):
            raise PermissionError(f"Cannot write to read-only mount: {dst}")
        self._vault.move(src, dst)

    def log(self, filepath: str):
        return self._vault.log(filepath)

    def read_version(self, filepath: str, version_id: str) -> bytes:
        return self._vault.read_version(filepath, version_id)

    def restore(self, filepath: str, version_id: str):
        return self._vault.restore(filepath, version_id)

    def begin_commit(self):
        self._vault.begin_commit()

    def end_commit(self, message: str, author: Optional[str] = None):
        self._vault.end_commit(message, author=author)

    def commit_log(self):
        return self._vault.commit_log()

    def revert_commit(self, commit_id: str):
        return self._vault.revert_commit(commit_id)
