from pathlib import Path

_IMAGE = "vim-sandbox:latest"
_DOCKERFILE = Path(__file__).parent.parent / "sandboxes" / "Dockerfile.vim"


async def run(*args):
    """Edit a file using vim inside a sandboxed Docker container.

    Usage: vim <file>
    """
    from system.context import SystemContext, cprint
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if len(args) == 0:
        cprint("Usage: vim <file>")
        return

    if len(args) > 1:
        cprint("vim: only single file editing is supported")
        return

    vault = ctx.fs()
    filepath = args[0]

    # Resolve the path to vault format
    _, vault_path = resolve_path(filepath, ctx.cwd)

    # Check if it's a directory
    if vault.exists(vault_path) and vault.is_dir(vault_path):
        cprint(f"vim: {filepath}: Is a directory")
        return

    # Check parent directory exists before proceeding
    if '/' in vault_path:
        parent = vault_path.rsplit('/', 1)[0]
        if not vault.is_dir(parent):
            cprint(f"vim: {filepath}: No such file or directory")
            return

    # If file exists, check it's not binary
    if vault.exists(vault_path):
        try:
            vault.read(vault_path).decode('utf-8')
        except UnicodeDecodeError:
            cprint(f"vim: {filepath}: Cannot edit binary file")
            return

    # Determine prefix and relative filename for the sandbox
    if '/' in vault_path:
        prefix = vault_path.rsplit('/', 1)[0]
        rel_name = vault_path.rsplit('/', 1)[1]
    else:
        prefix = ""
        rel_name = vault_path

    from bin.sandbox import run as sandbox_run

    sandbox_args = [
        "--image", _IMAGE,
        "--build", str(_DOCKERFILE),
    ]
    if prefix:
        sandbox_args.extend(["--prefix", prefix])
    sandbox_args.extend(["--cmd", f"vim {rel_name}"])

    await sandbox_run(*sandbox_args)
