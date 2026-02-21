"""FUSE filesystem implementation for AgentVault.

This module provides a FUSE filesystem that mounts a Vault as a regular filesystem.
"""

from __future__ import annotations

import errno
import logging
import os
import stat
import time
from typing import Any

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

from fs.vault import Vault


class VaultFS(LoggingMixIn, Operations):
    """FUSE filesystem for AgentVault.

    Mounts a Vault database as a filesystem, allowing standard file operations.
    """

    def __init__(self, vault: Vault):
        """Initialize the FUSE filesystem.

        :param vault: The Vault instance to expose as a filesystem
        """
        self.vault = vault
        self.fd = 0  # File descriptor counter

    def _get_directories(self) -> set[str]:
        """Get all virtual directories from file paths.

        Since the vault stores paths like "docs/file.txt" as strings,
        we need to extract the directory structure.
        """
        files = self.vault.list()
        dirs = {'/'}

        for filepath in files:
            parts = filepath.split('/')
            # Build all parent directories
            for i in range(1, len(parts)):
                dir_path = '/' + '/'.join(parts[:i])
                dirs.add(dir_path)

        return dirs

    def _path_to_vault_path(self, path: str) -> str:
        """Convert FUSE path to vault path.

        FUSE uses paths like "/docs/file.txt"
        Vault uses paths like "docs/file.txt"
        """
        if path.startswith('/'):
            path = path[1:]
        return path

    def _is_directory(self, path: str) -> bool:
        """Check if a path is a directory."""
        if path == '/':
            return True
        return path in self._get_directories()

    def _is_file(self, path: str) -> bool:
        """Check if a path is a file."""
        vault_path = self._path_to_vault_path(path)
        return vault_path in self.vault.list()

    def getattr(self, path: str, fh: Any = None) -> dict[str, Any]:
        """Get file attributes.

        :param path: File path
        :param fh: File handle (unused)
        :return: Dictionary of file attributes
        """
        now = time.time()

        # Root directory
        if path == '/':
            return {
                'st_mode': stat.S_IFDIR | 0o755,
                'st_nlink': 2,
                'st_size': 0,
                'st_ctime': now,
                'st_mtime': now,
                'st_atime': now,
            }

        # Check if it's a directory
        if self._is_directory(path):
            return {
                'st_mode': stat.S_IFDIR | 0o755,
                'st_nlink': 2,
                'st_size': 0,
                'st_ctime': now,
                'st_mtime': now,
                'st_atime': now,
            }

        # Check if it's a file
        if self._is_file(path):
            vault_path = self._path_to_vault_path(path)
            try:
                content = self.vault.read(vault_path)
                return {
                    'st_mode': stat.S_IFREG | 0o644,
                    'st_nlink': 1,
                    'st_size': len(content),
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_atime': now,
                }
            except FileNotFoundError:
                pass

        raise FuseOSError(errno.ENOENT)

    def readdir(self, path: str, fh: Any) -> list[str]:
        """Read directory contents.

        :param path: Directory path
        :param fh: File handle (unused)
        :return: List of entries in the directory
        """
        entries = ['.', '..']

        # Get all files and directories
        files = self.vault.list()
        dirs = self._get_directories()

        # Normalize the path for comparison
        if path == '/':
            prefix = ''
        else:
            prefix = path[1:] + '/'  # Remove leading /, add trailing /

        # Find direct children (files and dirs)
        seen = set()

        for filepath in files:
            # Check if this file is in the current directory
            if prefix and not filepath.startswith(prefix):
                continue

            # Get the relative path from current directory
            rel_path = filepath[len(prefix):] if prefix else filepath

            # Only include direct children (no /)
            if '/' not in rel_path:
                if rel_path not in seen:
                    entries.append(rel_path)
                    seen.add(rel_path)
            else:
                # This is in a subdirectory, add the subdirectory name
                subdir = rel_path.split('/')[0]
                if subdir not in seen:
                    entries.append(subdir)
                    seen.add(subdir)

        return entries

    def read(self, path: str, size: int, offset: int, fh: Any) -> bytes:
        """Read file data.

        :param path: File path
        :param size: Number of bytes to read
        :param offset: Offset to start reading from
        :param fh: File handle (unused)
        :return: File data
        """
        vault_path = self._path_to_vault_path(path)
        try:
            content = self.vault.read(vault_path)
            return content[offset:offset + size]
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)

    def write(self, path: str, data: bytes, offset: int, fh: Any) -> int:
        """Write file data.

        :param path: File path
        :param data: Data to write
        :param offset: Offset to start writing at
        :param fh: File handle (unused)
        :return: Number of bytes written
        """
        vault_path = self._path_to_vault_path(path)

        # Read existing content if file exists
        try:
            existing = self.vault.read(vault_path)
        except FileNotFoundError:
            existing = b''

        # Build new content with data at offset
        if offset > len(existing):
            # Pad with zeros if offset is beyond current size
            existing = existing + b'\x00' * (offset - len(existing))

        new_content = existing[:offset] + data + existing[offset + len(data):]
        self.vault.write(vault_path, new_content)

        return len(data)

    def create(self, path: str, mode: int) -> int:
        """Create a new file.

        :param path: File path
        :param mode: File mode (permissions)
        :return: File descriptor
        """
        vault_path = self._path_to_vault_path(path)
        self.vault.write(vault_path, b'')

        self.fd += 1
        return self.fd

    def unlink(self, path: str) -> None:
        """Delete a file.

        :param path: File path
        """
        vault_path = self._path_to_vault_path(path)
        self.vault.delete(vault_path)

    def truncate(self, path: str, length: int, fh: Any = None) -> None:
        """Truncate a file to a specified length.

        :param path: File path
        :param length: New file length
        :param fh: File handle (unused)
        """
        vault_path = self._path_to_vault_path(path)

        try:
            content = self.vault.read(vault_path)
        except FileNotFoundError:
            content = b''

        if length < len(content):
            new_content = content[:length]
        else:
            new_content = content + b'\x00' * (length - len(content))

        self.vault.write(vault_path, new_content)

    def mkdir(self, path: str, mode: int) -> None:
        """Create a directory.

        Directories are virtual in the vault - they exist implicitly
        through file paths. So this is a no-op.

        :param path: Directory path
        :param mode: Directory mode (permissions)
        """
        # Directories are virtual, no action needed
        pass

    def rmdir(self, path: str) -> None:
        """Remove a directory.

        Directories are virtual, so we check if it's empty.

        :param path: Directory path
        """
        # Check if directory has any files
        vault_prefix = self._path_to_vault_path(path) + '/'
        files = self.vault.list()

        for filepath in files:
            if filepath.startswith(vault_prefix):
                raise FuseOSError(errno.ENOTEMPTY)

        # Directory is empty (or doesn't exist), no action needed
        pass

    def open(self, path: str, flags: int) -> int:
        """Open a file.

        :param path: File path
        :param flags: Open flags
        :return: File descriptor
        """
        self.fd += 1
        return self.fd

    def release(self, path: str, fh: Any) -> None:
        """Release/close a file.

        :param path: File path
        :param fh: File handle
        """
        # No action needed
        pass


def mount(vault_path: str, user: str, mountpoint: str, foreground: bool = True) -> None:
    """Mount a vault as a FUSE filesystem.

    :param vault_path: Path to the vault database file
    :param user: Username for the vault partition
    :param mountpoint: Directory to mount the filesystem at
    :param foreground: Whether to run in foreground (default: True)
    """
    logging.basicConfig(level=logging.INFO)
    vault = Vault(vault_path, user)
    vaultfs = VaultFS(vault)
    FUSE(vaultfs, mountpoint, foreground=foreground, allow_other=True)


def main() -> None:
    """Command-line entry point for mounting a vault."""
    import sys

    if len(sys.argv) < 4:
        print("Usage: python -m fs.vaultfs <vault_db> <user> <mountpoint>")  # no-ctx-print
        print("Example: python -m fs.vaultfs /data/vault.db alice /mnt/vault")  # no-ctx-print
        sys.exit(1)

    vault_path = sys.argv[1]
    user = sys.argv[2]
    mountpoint = sys.argv[3]

    print(f"Mounting vault '{vault_path}' for user '{user}' at '{mountpoint}'...")  # no-ctx-print
    mount(vault_path, user, mountpoint)


if __name__ == '__main__':
    main()
