"""Disk usage command - estimate file space usage."""


def _format_size(size_bytes: int, human_readable: bool) -> str:
    """Format size in bytes to human-readable or byte format.

    :param size_bytes: Size in bytes
    :param human_readable: If True, format as KB/MB/GB, otherwise as bytes
    :return: Formatted size string
    """
    if not human_readable:
        return str(size_bytes)

    # Convert to human-readable format
    for unit in ['', 'K', 'M', 'G', 'T']:
        if size_bytes < 1024.0:
            if unit == '':
                return f"{size_bytes:.0f}"
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}P"


def _calculate_directory_sizes(vault, target_path: str) -> tuple[dict[str, int], dict[str, int]]:
    """Calculate current and total sizes for all directories under target_path.

    :param vault: The Vault or OverlayFS instance
    :param target_path: The directory path to analyze
    :return: Tuple of (current_sizes, total_sizes) - dictionaries mapping directory paths to sizes in bytes
    """
    import sqlite3

    # Extract the underlying Vault if we have an OverlayFS
    actual_vault = vault._vault if hasattr(vault, '_vault') else vault

    # Get current sizes (latest versions only)
    files = vault.list_with_metadata()

    # Normalize target path for comparison
    if target_path == '/' or target_path == '':
        prefix = ''
    else:
        target_path = target_path.lstrip('/')
        prefix = target_path + '/'

    # Dictionary to accumulate sizes: path -> total_size
    current_sizes = {}

    for file_meta in files:
        filepath = file_meta.filepath.lstrip('/')

        # Skip files not under target path
        if prefix and not filepath.startswith(prefix):
            continue

        # Get relative path from target
        rel_path = filepath[len(prefix):] if prefix else filepath

        # Add file size to all parent directories
        size = file_meta.size or 0

        # The target directory itself
        target_key = target_path if target_path else '.'
        current_sizes[target_key] = current_sizes.get(target_key, 0) + size

        # All parent directories under target
        parts = rel_path.split('/')
        for i in range(len(parts) - 1):  # Exclude the file itself
            # Build directory path
            dir_path = '/'.join(parts[:i+1])
            if target_path:
                full_dir_path = f"{target_path}/{dir_path}"
            else:
                full_dir_path = dir_path

            current_sizes[full_dir_path] = current_sizes.get(full_dir_path, 0) + size

    # Now calculate total sizes including all versions
    total_sizes = {}

    # Query all versions from the database
    conn = sqlite3.connect(actual_vault.filename)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT filepath, LENGTH(content)
           FROM versions
           WHERE user = ? AND hash != 'tombstone'""",
        (actual_vault.user,)
    )

    for filepath, size in cursor.fetchall():
        filepath = filepath.lstrip('/')

        # Skip files not under target path
        if prefix and not filepath.startswith(prefix):
            continue

        # Get relative path from target
        rel_path = filepath[len(prefix):] if prefix else filepath

        # The target directory itself
        target_key = target_path if target_path else '.'
        total_sizes[target_key] = total_sizes.get(target_key, 0) + size

        # All parent directories under target
        parts = rel_path.split('/')
        for i in range(len(parts) - 1):  # Exclude the file itself
            dir_path = '/'.join(parts[:i+1])
            if target_path:
                full_dir_path = f"{target_path}/{dir_path}"
            else:
                full_dir_path = dir_path

            total_sizes[full_dir_path] = total_sizes.get(full_dir_path, 0) + size

    conn.close()

    return current_sizes, total_sizes


async def run(*args):
    """Estimate file space usage.

    Usage: du [-s] [-h] [PATH...]

    Options:
      -s    Display only a total for each argument (summarize)
      -h    Human-readable output (e.g., 1K, 234M, 2G)

    Supports glob patterns like * and dir*

    Output format: CURRENT_SIZE  TOTAL_SIZE  PATH
      CURRENT_SIZE: Size of the latest version of files
      TOTAL_SIZE: Size including all historical versions
    """
    from system.context import SystemContext, cprint
    from fs.utils import resolve_path
    import fnmatch

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    # Parse flags
    summarize = False
    human_readable = False
    positional = []

    for arg in args:
        if arg == '-s':
            summarize = True
        elif arg == '-h':
            human_readable = True
        elif arg.startswith('-'):
            cprint(f"du: unknown option: {arg}")
            cprint("Usage: du [-s] [-h] [PATH...]")
            return
        else:
            positional.append(arg)

    vault = ctx.fs()

    # Expand glob patterns
    targets = []
    if not positional:
        # Default to current directory
        targets = [(ctx.cwd.lstrip('/'), '.')]
    else:
        # Expand each pattern
        for pattern in positional:
            # Check if pattern contains glob characters
            if '*' in pattern or '?' in pattern or '[' in pattern:
                # Expand the glob pattern
                _, vault_pattern = resolve_path(pattern, ctx.cwd)
                vault_pattern = vault_pattern.lstrip('/')

                # Get the directory part and the pattern part
                if '/' in vault_pattern:
                    dir_part = '/'.join(vault_pattern.split('/')[:-1])
                    pattern_part = vault_pattern.split('/')[-1]
                else:
                    dir_part = ctx.cwd.lstrip('/')
                    pattern_part = vault_pattern if vault_pattern else pattern

                # List files/dirs in the directory, filtered by prefix
                all_files = vault.list(prefix=dir_part)
                matched = set()

                # Match files and extract directory names
                prefix = dir_part + '/' if dir_part else ''
                for filepath in all_files:
                    filepath = filepath.lstrip('/')
                    if prefix:
                        if not filepath.startswith(prefix):
                            continue
                        rel_path = filepath[len(prefix):]
                    else:
                        rel_path = filepath

                    # Get the immediate child (file or first dir component)
                    if '/' in rel_path:
                        child = rel_path.split('/')[0]
                    else:
                        child = rel_path

                    # Match against pattern
                    if fnmatch.fnmatch(child, pattern_part):
                        full_path = prefix + child if prefix else child
                        matched.add(full_path)

                # Add matched paths as targets
                for match in sorted(matched):
                    # Use original pattern with matched name for display
                    if '/' in pattern:
                        display = '/'.join(pattern.split('/')[:-1] + [match.split('/')[-1]])
                    else:
                        display = match.split('/')[-1]
                    targets.append((match, display))

                if not matched:
                    cprint(f"du: {pattern}: No such file or directory")
            else:
                # Regular path (no glob)
                _, vault_path = resolve_path(pattern, ctx.cwd)
                targets.append((vault_path.lstrip('/'), pattern))

    # Process each target
    for target, display_name in targets:
        # Check if target is a file (not a directory)
        is_file = vault.exists(target) and not vault.is_dir(target)

        if is_file:
            # Handle individual file
            actual_vault = vault._vault if hasattr(vault, '_vault') else vault

            # Get current file size
            try:
                current_content = vault.read(target)
                current_size = len(current_content)
            except:
                current_size = 0

            # Get total size across all versions
            import sqlite3
            conn = sqlite3.connect(actual_vault.filename)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT SUM(LENGTH(content))
                   FROM versions
                   WHERE user = ? AND filepath = ? AND hash != 'tombstone'""",
                (actual_vault.user, target)
            )
            row = cursor.fetchone()
            total_size = row[0] if row and row[0] else 0
            conn.close()

            cprint(f"{_format_size(current_size, human_readable)}\t{_format_size(total_size, human_readable)}\t{display_name}")
            continue

        # Calculate directory sizes (current and total)
        current_sizes, total_sizes = _calculate_directory_sizes(vault, target)

        if not current_sizes and not total_sizes:
            # No files found
            cprint(f"{_format_size(0, human_readable)}\t{_format_size(0, human_readable)}\t{display_name}")
            continue

        if summarize or len(targets) > 1:
            # Only show the total for the target directory
            # (always summarize when multiple targets like with globs)
            target_key = target if target else '.'
            current = current_sizes.get(target_key, 0)
            total = total_sizes.get(target_key, 0)
            cprint(f"{_format_size(current, human_readable)}\t{_format_size(total, human_readable)}\t{display_name}")
        else:
            # Show all subdirectories, sorted by path
            all_dirs = set(current_sizes.keys()) | set(total_sizes.keys())
            sorted_dirs = sorted(all_dirs)

            for dir_path in sorted_dirs:
                current = current_sizes.get(dir_path, 0)
                total = total_sizes.get(dir_path, 0)

                # Convert internal path to display path
                if target:
                    # Remove target prefix for display
                    if dir_path == target:
                        display = display_name
                    elif dir_path.startswith(target + '/'):
                        rel = dir_path[len(target)+1:]
                        display = f"{display_name}/{rel}"
                    else:
                        continue
                else:
                    display = f"./{dir_path}" if dir_path != '.' else '.'

                cprint(f"{_format_size(current, human_readable)}\t{_format_size(total, human_readable)}\t{display}")
