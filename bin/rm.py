_USAGE = """\
rm - Remove files or directories

Usage: rm [-r] [-h] FILE [FILE ...]

Options:
  -r    Remove directories and their contents recursively
  -h    Show this help message

FILE may contain glob patterns (*, ?, [...]) to match multiple paths."""


async def run(*args):
    """Remove files or directories."""
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

    # Parse flags
    recursive = False
    files_to_remove = []

    for arg in args:
        if arg == "-r" or arg == "-R":
            recursive = True
        elif arg.startswith("-"):
            cprint(f"rm: invalid option -- '{arg[1:]}'")
            cprint(_USAGE)
            return
        else:
            files_to_remove.append(arg)

    if len(files_to_remove) == 0:
        cprint(_USAGE)
        return

    # Remove each file/directory, expanding glob patterns where present
    for filepath in files_to_remove:
        has_globs = any(c in filepath for c in _GLOB_CHARS)
        vault_paths = glob_paths(filepath, ctx.cwd, vault)

        if has_globs and not vault_paths:
            cprint(f"rm: no matches for '{filepath}'")
            continue

        for vault_path in vault_paths:
            # Check if path exists
            if not vault.exists(vault_path):
                cprint(f"rm: cannot remove '{filepath}': No such file or directory")
                continue

            # Check if it's a directory
            if vault.is_dir(vault_path):
                if not recursive:
                    cprint(f"rm: cannot remove '{filepath}': Is a directory")
                    continue

                # Remove all files in the directory
                all_files = vault.list(prefix=vault_path)
                prefix = vault_path + '/'
                files_in_dir = [f for f in all_files if f.startswith(prefix) or f == vault_path]

                if not files_in_dir:
                    # Empty directory (virtual), nothing to do
                    continue

                # Delete all files in the directory
                for file in files_in_dir:
                    try:
                        vault.delete(file)
                    except Exception as e:
                        cprint(f"rm: cannot remove '{file}': {e}")
            else:
                # It's a file, delete it
                try:
                    vault.delete(vault_path)
                except FileNotFoundError:
                    cprint(f"rm: cannot remove '{filepath}': No such file or directory")
                except Exception as e:
                    cprint(f"rm: cannot remove '{filepath}': {e}")
