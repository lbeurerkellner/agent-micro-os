async def run(*args):
    """Display file version history, or show content of a specific revision."""
    from system.context import SystemContext
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        print("No context found. Please run this command within a SystemContext.")
        return

    if len(args) == 0:
        print("Usage: log <file> [revision-uuid]")
        return

    vault = ctx.fs()
    filepath = args[0]
    version_id = args[1] if len(args) > 1 else None

    # Resolve the path to vault format
    _, vault_path = resolve_path(filepath, ctx.cwd)

    # Check if file exists
    if not vault.exists(vault_path):
        print(f"log: {filepath}: No such file or directory")
        return

    # Check if it's a directory
    if vault.is_dir(vault_path):
        print(f"log: {filepath}: Is a directory")
        return

    try:
        if version_id:
            # Show content of a specific revision
            content = vault.read_version(vault_path, version_id)
            if isinstance(content, bytes):
                print(content.decode("utf-8", errors="replace"))
            else:
                print(content)
        else:
            # Show version log
            print(vault_path)
            for version in vault.log(vault_path):
                print(version.version_id, version.author, version.timestamp)
    except ValueError as e:
        print(f"log: {e}")
    except FileNotFoundError:
        print(f"log: {filepath}: No such file or directory")
    except Exception as e:
        print(f"log: {filepath}: {e}")
