"""Utility functions for file system operations."""

import fnmatch
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


_GLOB_CHARS = frozenset('*?[')


def glob_paths(pattern: str, cwd: str, vault) -> list[str]:
    """Resolve a glob pattern to matching vault paths.

    Args:
        pattern: File path pattern, possibly containing glob characters (*, ?, [...])
        cwd: Current working directory
        vault: Vault instance used to list files when the pattern contains globs

    Returns:
        For non-glob patterns: a single-element list with the resolved vault path
        (regardless of whether it exists — callers should check existence).
        For glob patterns: a list of existing vault paths that match the pattern.
    """
    if not any(c in pattern for c in _GLOB_CHARS):
        _, vault_path = resolve_path(pattern, cwd)
        return [vault_path]

    # Build an absolute pattern so we can match against absolute vault paths.
    if pattern.startswith('/'):
        abs_pattern = pattern
    else:
        abs_pattern = (cwd.rstrip('/') + '/' + pattern) if cwd != '/' else '/' + pattern

    # Normalise (handles .., extra slashes) without disturbing glob chars.
    # os.path.normpath is safe here — it won't expand globs.
    abs_pattern = os.path.normpath(abs_pattern)
    if not abs_pattern.startswith('/'):
        abs_pattern = '/' + abs_pattern

    vault_pattern = abs_pattern.lstrip('/')

    # Determine the longest literal prefix so we can narrow the vault listing.
    parts = vault_pattern.split('/')
    prefix_parts: list[str] = []
    for part in parts:
        if any(c in part for c in _GLOB_CHARS):
            break
        prefix_parts.append(part)
    prefix = '/'.join(prefix_parts)

    all_files = vault.list(prefix=prefix)
    return [f for f in all_files if fnmatch.fnmatch(f, vault_pattern)]