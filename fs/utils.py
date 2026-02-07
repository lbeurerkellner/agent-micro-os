"""Utility functions for file system operations."""

import os


def resolve_path(filepath: str, cwd: str) -> tuple[str, str]:
    """Resolve a file path to both absolute and vault paths.

    Args:
        filepath: The file path to resolve (absolute or relative)
        cwd: Current working directory

    Returns:
        A tuple of (absolute_path, vault_path) where:
        - absolute_path: Normalized path starting with /
        - vault_path: Path without leading / (as stored in vault)
    """
    # Handle absolute vs relative paths
    if filepath.startswith('/'):
        # Absolute path
        target_path = filepath
    else:
        # Relative path - join with current directory
        if cwd == '/':
            target_path = '/' + filepath
        else:
            target_path = cwd + '/' + filepath

    # Normalize the path (remove redundant slashes, handle . and ..)
    target_path = os.path.normpath(target_path)

    # Ensure it starts with /
    if not target_path.startswith('/'):
        target_path = '/' + target_path

    # Remove leading slash for vault operations (vault stores paths without leading /)
    vault_path = target_path.lstrip('/')

    return target_path, vault_path