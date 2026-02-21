async def run(*args):
    """Display file version history, or show content of a specific revision."""
    from system.context import SystemContext, cprint
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if len(args) == 0:
        cprint("Usage: log <file> [revision-uuid]")
        return

    vault = ctx.fs()
    filepath = args[0]
    version_id = args[1] if len(args) > 1 else None

    # Resolve the path to vault format
    _, vault_path = resolve_path(filepath, ctx.cwd)

    # Check if file exists
    if not vault.exists(vault_path):
        cprint(f"log: {filepath}: No such file or directory")
        return

    # Check if it's a directory
    if vault.is_dir(vault_path):
        cprint(f"log: {filepath}: Is a directory")
        return

    try:
        if version_id:
            # Show content of a specific revision
            content = vault.read_version(vault_path, version_id)
            if isinstance(content, bytes):
                cprint(content.decode("utf-8", errors="replace"))
            else:
                cprint(content)
        else:
            # Show version log
            cprint(vault_path)
            for version in vault.log(vault_path):
                cprint(version.version_id, version.author, version.timestamp)
    except ValueError as e:
        cprint(f"log: {e}")
    except FileNotFoundError:
        cprint(f"log: {filepath}: No such file or directory")
    except Exception as e:
        cprint(f"log: {filepath}: {e}")
