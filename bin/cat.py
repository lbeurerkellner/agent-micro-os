async def run(*args):
    """Display file contents."""
    from system.context import SystemContext
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        print("No context found. Please run this command within a SystemContext.")
        return

    if len(args) == 0:
        print("Usage: cat <file> [file2 ...]")
        return

    vault = ctx.fs()

    for filepath in args:
        # Resolve the path to vault format
        _, vault_path = resolve_path(filepath, ctx.cwd)

        # Check if file exists
        if not vault.exists(vault_path):
            print(f"cat: {filepath}: No such file or directory")
            continue

        # Check if it's a directory
        if vault.is_dir(vault_path):
            print(f"cat: {filepath}: Is a directory")
            continue

        # Read and display file contents
        try:
            content = vault.read(vault_path)
            # Print as string if valid UTF-8, otherwise print as bytes
            try:
                print(content.decode('utf-8'), end='\n')
            except UnicodeDecodeError:
                # Binary file - print bytes representation or hex dump
                print(f"<binary data: {len(content)} bytes>")
        except FileNotFoundError:
            print(f"cat: {filepath}: No such file or directory")
        except Exception as e:
            print(f"cat: {filepath}: {e}")
