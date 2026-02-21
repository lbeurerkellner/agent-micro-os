async def run(*args):
    """Copy files or directories."""
    from system.context import SystemContext, cprint
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if len(args) < 2:
        cprint("Usage: cp <source> <destination>")
        return

    # Parse flags
    positional = []
    for arg in args:
        if arg.startswith("-"):
            cprint(f"cp: invalid option -- '{arg[1:]}'")
            cprint("Usage: cp <source> <destination>")
            return
        else:
            positional.append(arg)

    if len(positional) != 2:
        cprint("Usage: cp <source> <destination>")
        return

    src, dst = positional
    vault = ctx.fs()

    # Resolve paths
    _, src_vault = resolve_path(src, ctx.cwd)
    _, dst_vault = resolve_path(dst, ctx.cwd)

    # Check if source exists
    if not vault.exists(src_vault):
        cprint(f"cp: cannot stat '{src}': No such file or directory")
        return

    try:
        vault.copy(src_vault, dst_vault)
    except FileNotFoundError:
        cprint(f"cp: cannot stat '{src}': No such file or directory")
    except PermissionError as e:
        cprint(f"cp: {e}")
    except Exception as e:
        cprint(f"cp: {e}")
