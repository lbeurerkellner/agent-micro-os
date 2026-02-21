_USAGE = """\
cat - Display file contents

Usage: cat [-h] FILE [FILE ...]

Options:
  -h    Show this help message

FILE may contain glob patterns (*, ?, [...]) to match multiple paths."""


async def run(*args):
    """Display file contents."""
    from system.context import SystemContext, cprint
    from fs.utils import glob_paths, _GLOB_CHARS

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if not args or args[0] == '-h':
        cprint(_USAGE)
        return

    vault = ctx.fs()

    for filepath in args:
        has_globs = any(c in filepath for c in _GLOB_CHARS)
        vault_paths = glob_paths(filepath, ctx.cwd, vault)

        if has_globs and not vault_paths:
            cprint(f"cat: no matches for '{filepath}'")
            continue

        for vault_path in vault_paths:
            # Check if file exists
            if not vault.exists(vault_path):
                cprint(f"cat: {filepath}: No such file or directory")
                continue

            # Check if it's a directory
            if vault.is_dir(vault_path):
                cprint(f"cat: {filepath}: Is a directory")
                continue

            # Read and display file contents
            try:
                content = vault.read(vault_path)
                # Print as string if valid UTF-8, otherwise print as bytes
                try:
                    cprint(content.decode('utf-8'), end='\n')
                except UnicodeDecodeError:
                    # Binary file - print bytes representation or hex dump
                    cprint(f"<binary data: {len(content)} bytes>")
            except FileNotFoundError:
                cprint(f"cat: {filepath}: No such file or directory")
            except Exception as e:
                cprint(f"cat: {filepath}: {e}")
