from fs.utils import resolve_path

def _list_directory(vault, path: str) -> list[str]:
    """List files and directories in a specific path.

    Similar to VaultFS.readdir() implementation.

    :param vault: The Vault instance
    :param path: The directory path to list (e.g., '/', '/docs', '/docs/reports')
    :return: List of file and directory names (not full paths)
    """
    # Get all files from the vault
    files = vault.list()

    # Normalize the path for comparison
    if path == '/' or path == '':
        prefix = ''
    else:
        # Remove leading slash if present, add trailing slash
        path = path.lstrip('/')
        prefix = path + '/'

    # Find direct children (files and dirs)
    entries = []
    seen = set()

    for filepath in files:
        # Strip any leading slashes from vault paths (they shouldn't have them, but just in case)
        filepath = filepath.lstrip('/')

        # Check if this file is in the current directory
        if prefix and not filepath.startswith(prefix):
            continue

        # Get the relative path from current directory
        rel_path = filepath[len(prefix):] if prefix else filepath

        # Skip empty paths
        if not rel_path:
            continue

        # Only include direct children (no /)
        if '/' not in rel_path:
            # This is a direct file in the current directory
            if rel_path not in seen:
                entries.append(rel_path)
                seen.add(rel_path)
        else:
            # This is in a subdirectory, add the subdirectory name
            subdir = rel_path.split('/')[0]
            # Skip empty subdirectory names
            if subdir and subdir not in seen:
                entries.append(subdir + '/')  # Add trailing slash to indicate directory
                seen.add(subdir)

    return sorted(entries)


def _list_directory_with_timestamps(vault, path: str) -> list[tuple[str, str | None]]:
    """List files/directories with timestamps for files.

    :param vault: The Vault instance
    :param path: The directory path to list
    :return: Sorted list of (name, timestamp) tuples. Directories have None timestamp.
    """
    metas = vault.list_with_metadata()
    # Build lookup from full filepath to timestamp
    ts_by_path = {m.filepath: m.timestamp for m in metas}

    if path == '/' or path == '':
        prefix = ''
    else:
        path = path.lstrip('/')
        prefix = path + '/'

    entries = []
    seen = set()

    for filepath in ts_by_path:
        filepath_clean = filepath.lstrip('/')

        if prefix and not filepath_clean.startswith(prefix):
            continue

        rel_path = filepath_clean[len(prefix):] if prefix else filepath_clean

        if not rel_path:
            continue

        if '/' not in rel_path:
            if rel_path not in seen:
                entries.append((rel_path, ts_by_path[filepath]))
                seen.add(rel_path)
        else:
            subdir = rel_path.split('/')[0]
            if subdir and subdir not in seen:
                entries.append((subdir + '/', None))
                seen.add(subdir)

    # Sort: files by timestamp descending (most recent first), directories last
    return sorted(entries, key=lambda e: (e[1] is not None, e[1] or ''), reverse=True)


async def run(*args):
    """List files in the current directory."""
    from system.context import SystemContext

    ctx = SystemContext.current()
    if not ctx:
        print("No context found. Please run this command within a SystemContext.")
        return

    # Parse flags
    show_timestamps = False
    positional = []
    for arg in args:
        if arg == '-t':
            show_timestamps = True
        elif arg.startswith('-'):
            print(f"ls: unknown option: {arg}")
            return
        else:
            positional.append(arg)

    if len(positional) > 1:
        print("Usage: ls [-t] [DIRECTORY]")
        return

    vault = ctx.fs()
    target = ctx.cwd if not positional else resolve_path(positional[0], ctx.cwd)[1]

    if show_timestamps:
        entries = _list_directory_with_timestamps(vault, target)
        if not entries:
            return
        for name, ts in entries:
            if ts:
                print(f"{ts}  {name}")
            else:
                print(f"{'':>19}  {name}")
    else:
        entries = _list_directory(vault, target)
        if not entries:
            return
        for entry in entries:
            print(entry)