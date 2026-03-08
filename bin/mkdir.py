_USAGE = """\
mkdir - Create directories

Usage: mkdir [-h] DIR [DIR ...]

Options:
  -h    Show this help message

Creates directories in the vault. Parent directories are created
automatically (like mkdir -p)."""


async def run(*args):
    """Create directories."""
    from system.context import SystemContext, cprint
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if not args or args[0] == "-h":
        cprint(_USAGE)
        return

    vault = ctx.fs()

    for arg in args:
        if arg.startswith("-"):
            cprint(f"mkdir: invalid option -- '{arg[1:]}'")
            cprint(_USAGE)
            return

        _, vault_path = resolve_path(arg, ctx.cwd)

        try:
            vault.mkdir(vault_path)
        except ValueError as e:
            cprint(f"mkdir: cannot create directory '{arg}': {e}")
        except Exception as e:
            cprint(f"mkdir: {arg}: {e}")
