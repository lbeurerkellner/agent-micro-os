import os


_CAP_SCRIPT = """\
#!/usr/bin/env cap
# ---
# name: vim-editor
# description: Vim text editor
# dependencies: ['apt:vim']
# access: ['**:rw']
# user: 1000
# runtime: shell
# ---

exec vim "$@"
"""


async def run(*args):
    """Edit a file using vim inside a cap-managed sandbox.

    Usage: vim <file>
    """
    import shutil
    import tempfile

    from bin.sandbox import (
        _build_snapshot,
        _diff_and_commit,
        _diff_from_dir,
        _export_to_dir,
    )
    from fs.utils import resolve_path
    from fs.vault import Vault
    from system.context import SystemContext, cprint

    ctx = SystemContext.current()
    if not ctx:
        cprint("vim: no context")
        return

    if len(args) == 0:
        cprint("Usage: vim <file>")
        return

    if len(args) > 1:
        cprint("vim: only single file editing is supported")
        return

    vault_fs = ctx.fs()
    filepath = args[0]

    # Resolve the path to vault format
    _, vault_path = resolve_path(filepath, ctx.cwd)

    # Check if it's a directory
    if vault_fs.exists(vault_path) and vault_fs.is_dir(vault_path):
        cprint(f"vim: {filepath}: Is a directory")
        return

    # Check parent directory exists
    if '/' in vault_path:
        parent = vault_path.rsplit('/', 1)[0]
        if not vault_fs.is_dir(parent):
            cprint(f"vim: {filepath}: No such file or directory")
            return

    # If file exists, check it's not binary
    if vault_fs.exists(vault_path):
        try:
            vault_fs.read(vault_path).decode('utf-8')
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

    # Build the vault snapshot
    vault = Vault(ctx.fsimage, ctx.user)
    snapshot = _build_snapshot(vault_fs, prefix, agents_md_name=None)
    tmpdir = tempfile.mkdtemp(prefix="vault-vim-")
    _export_to_dir(snapshot, tmpdir)

    # Write the cap script to a stable temp location
    cap_dir = os.path.join(tempfile.gettempdir(), "cap-vault")
    os.makedirs(cap_dir, exist_ok=True)
    cap_path = os.path.join(cap_dir, "vim-editor.cap.sh")
    with open(cap_path, "w") as f:
        f.write(_CAP_SCRIPT)

    try:
        saved_cwd = os.getcwd()
        os.chdir(tmpdir)
        from lib.cap.cap import main as cap_main
        try:
            cap_main(["--quiet", cap_path, rel_name])
        except SystemExit as e:
            if e.code and e.code != 0:
                cprint(f"vim: cap exited with code {e.code}")
                return False
        finally:
            os.chdir(saved_cwd)

        # Diff and commit changes back
        vault_prefix = (prefix.strip("/") + "/") if prefix.strip("/") else ""
        current = _diff_from_dir(tmpdir, snapshot)
        _diff_and_commit(vault, snapshot, current, prefix=vault_prefix)

        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        if os.path.exists(cap_path):
            os.unlink(cap_path)
