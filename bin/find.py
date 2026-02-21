from fs.utils import resolve_path


def _find_files(vault, path: str) -> list[str]:
    """Recursively list all files under a directory path.

    :param vault: The Vault/OverlayFS instance
    :param path: The directory path to search under (e.g., '/', '/docs')
    :return: Sorted list of file paths (relative to vault root, no leading slash)
    """
    if path == '/' or path == '':
        search_prefix = ''
    else:
        search_prefix = path.lstrip('/')

    files = vault.list(prefix=search_prefix)
    prefix = (search_prefix + '/') if search_prefix else ''

    result = []
    for filepath in files:
        filepath = filepath.lstrip('/')
        if prefix and not filepath.startswith(prefix):
            continue
        result.append(filepath)

    return sorted(result)


async def run(*args):
    """Recursively list files under a directory."""
    from system.context import SystemContext, cprint

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if len(args) > 1:
        cprint("Usage: find [DIRECTORY]")
        return

    vault = ctx.fs()

    if len(args) == 0:
        # No argument: search from cwd, prefix output with ./
        search_path = ctx.cwd
        entries = _find_files(vault, search_path)
        # Make paths relative to cwd
        cwd = ctx.cwd.lstrip('/')
        cwd_prefix = (cwd + '/') if cwd else ''
        for entry in entries:
            rel = entry[len(cwd_prefix):] if cwd_prefix else entry
            cprint(f"./{rel}")
    else:
        # Argument given: resolve path, display relative to user's argument
        arg = args[0]
        target_abs, target_vault = resolve_path(arg, ctx.cwd)
        entries = _find_files(vault, target_abs)
        # Strip the resolved vault prefix, re-add the user's argument as prefix
        vault_prefix = (target_vault + '/') if target_vault else ''
        arg_prefix = arg.strip('/') + '/' if arg.strip('/') else ''
        for entry in entries:
            rel = entry[len(vault_prefix):] if vault_prefix else entry
            cprint(f"{arg_prefix}{rel}")
