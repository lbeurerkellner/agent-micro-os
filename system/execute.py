from fs.utils import resolve_path
from fs.overlay import OverlayFS

from system.context import cprint
from system.program import parse, run

async def execute(ctx, filepath, *args):
    vault: OverlayFS = ctx.fs()

    # Resolve the path to vault format
    _, vault_path = resolve_path(filepath, ctx.cwd)

    # Check if file exists
    if not vault.exists(vault_path):
        cprint(f"{filepath}: No such file or directory", file=ctx.stderr)
        return

    # Check if it's a directory
    if vault.is_dir(vault_path):
        cprint(f"{filepath} is a directory", file=ctx.stderr)
        return

    try:
        # get contents
        contents = vault.read(vault_path).decode('utf-8')
    except Exception as e:
        cprint(f"Error executing {filepath}: {str(e)}", file=ctx.stderr)
        return

    # Check for shebang (#!)
    if contents.startswith('#!'):
        # Extract the shebang line
        first_line, _, rest = contents.partition('\n')
        shebang = first_line[2:].strip()  # Remove #! and whitespace

        # Check if it's an ash script
        if shebang in ['/sbin/ash', '/bin/ash', 'ash']:
            # Execute as ash script (line-by-line)
            from bin.ash import run_script
            try:
                # get content, replacing all $@ with the arguments
                await run_script(rest)
            except Exception as e:
                cprint(f"Error running ash script {filepath}: {str(e)}", file=ctx.stderr)
            return

        # Check if it's a cap tool
        if shebang in ['/usr/bin/env cap', 'cap']:
            await _run_cap_tool(ctx, filepath, contents, *args)
            return

        cprint(f"{filepath}: unsupported interpreter", file=ctx.stderr)
        return

    # check for .PROMPT directive (may appear after other directives like .ENGINE, .BUDGET)
    if "\n.PROMPT\n" not in contents and not contents.startswith(".PROMPT\n"):
        cprint(f"{filepath} is not executable", file=ctx.stderr)
        return

    # parse the prompt program
    try:
        program = parse(contents)
    except Exception as e:
        cprint(f"Error parsing {filepath}: {str(e)}", file=ctx.stderr)
        return

    # run the program
    try:
        await run(program, filepath, *args)
    except Exception as e:
        cprint(f"Error running {filepath}: {str(e)}", file=ctx.stderr)
        return


def _build_cap_snapshot(fs, access, args, cwd):
    """Build a selective snapshot containing only files matched by access entries.

    Explicit paths (vault-absolute like ``/var/experiences``) are resolved from
    the vault root.  ``$@`` entries resolve CLI args relative to *cwd*.

    Returns ``(snapshot, rewritten_args)`` where snapshot is
    ``{vault_rel_path: bytes}`` and rewritten_args has ``$@`` paths made
    vault-root-relative.
    """
    from fnmatch import fnmatch
    import posixpath

    snapshot = {}
    cwd_prefix = cwd.strip("/") if cwd else ""
    resolved_args = {}  # arg -> vault-root-relative path (only for args that exist)

    for entry in access:
        raw = entry
        if raw.endswith((":ro", ":rw")):
            raw = raw[:-3]

        if raw.startswith("$@"):
            # Resolve each CLI arg relative to cwd
            for arg in args:
                if arg.startswith("-"):
                    continue
                vault_path = f"{cwd_prefix}/{arg}" if cwd_prefix else arg
                vault_path = posixpath.normpath(vault_path).strip("/")
                if vault_path == ".":
                    vault_path = ""
                if fs.exists(vault_path):
                    resolved_args[arg] = vault_path if vault_path else "."
                    if fs.is_dir(vault_path):
                        for f in fs.list(prefix=vault_path):
                            snapshot[f] = fs.read(f)
                    else:
                        snapshot[vault_path] = fs.read(vault_path)
        else:
            # Vault-absolute path — strip leading /
            vault_path = raw.lstrip("/")
            if fs.exists(vault_path):
                if fs.is_dir(vault_path):
                    for f in fs.list(prefix=vault_path):
                        snapshot[f] = fs.read(f)
                else:
                    snapshot[vault_path] = fs.read(vault_path)
            # Also match as a glob pattern
            else:
                for f in fs.list():
                    if fnmatch(f, vault_path):
                        snapshot[f] = fs.read(f)

    # Rewrite $@ args to vault-root-relative paths (only args that resolved)
    rewritten_args = []
    for arg in args:
        if arg in resolved_args:
            rewritten_args.append(resolved_args[arg])
        else:
            rewritten_args.append(arg)

    return snapshot, rewritten_args


async def _run_cap_tool(ctx, filepath, contents, *args):
    """Run a cap-frontmatter tool by exporting the vault and invoking ``cap``."""
    import os
    import shutil
    import tempfile

    from bin.sandbox import (
        _diff_and_commit,
        _diff_from_dir,
        _export_to_dir,
    )
    from cap import run_script as cap_run_content
    from fs.vault import Vault

    from system.tools import parse_cap_meta

    fs = ctx.fs()
    vault = Vault(ctx.fsimage, ctx.user)
    meta, _ = parse_cap_meta(contents)

    # Validate access paths: all must be vault-absolute except "$@" entries.
    access = meta.get("access") or []
    for entry in access:
        raw = entry.split(":")[0] if ":" in entry else entry
        if not raw.startswith("/") and not raw.startswith("$@"):
            cprint(f"{filepath}: relative access path '{entry}' not allowed — use vault-absolute paths (e.g. '/{raw}')", file=ctx.stderr)
            return

    # Build selective snapshot — only files matched by access entries.
    snapshot, rewritten_args = _build_cap_snapshot(fs, access, args, ctx.cwd)
    tmpdir = tempfile.mkdtemp(prefix="vault-cap-")
    _export_to_dir(snapshot, tmpdir)

    # Strip leading "/" from access paths so cap sees them as relative
    # to its workspace root.
    if any(e.startswith("/") for e in access):
        normed = [e.lstrip("/") for e in access]
        contents = contents.replace(repr(access), repr(normed))

    # Derive a stable tool name from the filepath for consistent image tags.
    tool_name = filepath.rsplit("/", 1)[-1] if "/" in filepath else filepath

    try:
        result = cap_run_content(
            contents,
            rewritten_args,
            name=tool_name,
            cwd=tmpdir,
            interactive=ctx.interactive,
            capture=not ctx.interactive,
            quiet_sync=True,
        )

        if not ctx.interactive:
            if result.stdout.strip():
                cprint(result.stdout.strip())
            if result.stderr.strip():
                cprint(result.stderr.strip(), file=ctx.stderr)

        # Diff and commit changes back — no prefix since snapshot paths
        # are already vault-root-relative.
        current = _diff_from_dir(tmpdir, snapshot)
        _diff_and_commit(vault, snapshot, current, prefix="", quiet=False)
    except Exception as e:
        cprint(f"Error running cap tool {filepath}: {str(e)}", file=ctx.stderr)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


