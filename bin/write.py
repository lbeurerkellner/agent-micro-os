_USAGE = """\
write - Write content to a file

Usage: write [-h] FILE CONTENT

Options:
  -h    Show this help message

Arguments:
  FILE     Path to the file to write
  CONTENT  The content to write to the file.

Example:
  write /path/to/file "line one\\nline two\\nline three"
"""


async def run(*args):
    """Write content to a file."""
    from system.context import SystemContext, cprint
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if not args or args[0] == '-h':
        cprint(_USAGE)
        return

    if len(args) < 2:
        cprint("write: missing operand")
        cprint("Try 'write -h' for more information.")
        return

    filepath = args[0]
    content = ' '.join(args[1:])

    # Process escape sequences (\n, \t, etc.) that survive shlex parsing
    try:
        content = content.encode('raw_unicode_escape').decode('unicode_escape')
    except Exception:
        pass

    _, vault_path = resolve_path(filepath, ctx.cwd)

    # Check parent directory exists
    if '/' in vault_path:
        parent = vault_path.rsplit('/', 1)[0]
        if not ctx.fs().is_dir(parent):
            cprint(f"write: {filepath}: No such file or directory")
            return

    try:
        ctx.fs().write(vault_path, content.encode('utf-8'), parents=False)
        cprint(f"Wrote to {filepath}")
    except Exception as e:
        cprint(f"write: {filepath}: {e}")
