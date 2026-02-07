async def run(*args):
    """Remove files or directories."""
    from system.context import SystemContext
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        print("No context found. Please run this command within a SystemContext.")
        return

    if len(args) == 0:
        print("Usage: rm [-r] <file> [file2 ...]")
        return

    vault = ctx.fs()

    # Parse flags
    recursive = False
    files_to_remove = []

    for arg in args:
        if arg == "-r" or arg == "-R":
            recursive = True
        elif arg.startswith("-"):
            print(f"rm: invalid option -- '{arg[1:]}'")
            print("Usage: rm [-r] <file> [file2 ...]")
            return
        else:
            files_to_remove.append(arg)

    if len(files_to_remove) == 0:
        print("Usage: rm [-r] <file> [file2 ...]")
        return

    # Remove each file/directory
    for filepath in files_to_remove:
        # Resolve the path to vault format
        _, vault_path = resolve_path(filepath, ctx.cwd)

        # Check if path exists
        if not vault.exists(vault_path):
            print(f"rm: cannot remove '{filepath}': No such file or directory")
            continue

        # Check if it's a directory
        if vault.is_dir(vault_path):
            if not recursive:
                print(f"rm: cannot remove '{filepath}': Is a directory")
                continue

            # Remove all files in the directory
            all_files = vault.list()
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
                    print(f"rm: cannot remove '{file}': {e}")
        else:
            # It's a file, delete it
            try:
                vault.delete(vault_path)
            except FileNotFoundError:
                print(f"rm: cannot remove '{filepath}': No such file or directory")
            except Exception as e:
                print(f"rm: cannot remove '{filepath}': {e}")
