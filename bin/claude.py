import os
import shlex
import uuid

from system.context import cprint

_USAGE = """\
claude - Run the Claude Code agent in a sandboxed environment

When this command completes, the changes will be committed back to this workspace automatically. When the agent creates e.g. a file at /workspace/path/to/file.txt, it will be saved back to the vault at /path/to/file.txt.

When communicating to the user about what 'claude' did, always omit the /workspace prefix.

Usage: claude PROMPT
"""

_NO_VERSION_GLOBS = [
    "agent/.claude/.claude.json",
    "agent/.claude/.credentials.json",
    "agent/.claude/projects/**/*.jsonl",
    "agent/.claude/settings.json",
]

_IGNORE_GLOBS = [
    "agent/.claude/**",
    "CLAUDE.md",
]


def _build_cap_script(env: dict):
    """Generate a .cap.sh script for running Claude Code.

    Environment variables are baked into the script body because cap injects
    only ``secrets`` as ``-e`` flags to Docker — arbitrary env vars set on the
    host do not reach the container.
    """
    env_lines = "\n".join(f"export {k}={shlex.quote(v)}" for k, v in env.items())
    return f"""\
#!/usr/bin/env cap
# ---
# name: claude-agent
# description: Claude Code agent
# dependencies: ['npm:@anthropic-ai/claude-code', 'apt:gh', 'apt:jq', 'apt:ripgrep', 'apt:git', 'apt:less']
# access: ['**:rw']
# network: '*'
# user: 1000
# runtime: shell
# ---

# Environment setup (replaces what Dockerfile.claude used to bake in)
export HOME=/home/capuser
export PATH="/workspace/bin:$PATH"
export CLAUDE_DANGEROUSLY_SKIP_CONFIRMATIONS=1
{env_lines}

exec claude "$@"
"""


async def run(*args, env: dict = None, readonly=False, quiet=False, access=None):
    """Run the claude CLI in a cap-managed Docker container.

    Usage: claude [--prefix PATH] [claude-args...]

    Builds the container image via cap (two-stage cached Docker build with
    npm:@anthropic-ai/claude-code as a dependency), then mounts the vault
    snapshot and runs claude inside it.

    Options:
        --prefix PATH   Vault path to mount at /workspace (default: cwd)

    Args:
        *args: Remaining arguments are forwarded verbatim to the claude CLI.
        env: Optional extra environment variables for the container.
             ANTHROPIC_API_KEY is forwarded automatically when set in the host env.
        readonly: If True, do not commit changes back to the vault.
    """
    import shutil
    import tempfile

    from bin.sandbox import (
        _build_snapshot,
        _diff_and_commit,
        _diff_from_dir,
        _export_to_dir,
    )
    from cap import run_script as cap_run_content
    from fs.vault import Vault
    from system.context import SystemContext

    ctx = SystemContext.current()
    if not ctx:
        cprint("claude: no context")
        return

    tool_use_mode = not ctx.interactive

    # Parse optional --prefix; everything else goes to claude
    prefix = ""
    claude_args = []
    i = 0
    arg_list = list(args)
    while i < len(arg_list):
        if arg_list[i] == "--prefix" and i + 1 < len(arg_list):
            prefix = arg_list[i + 1]
            i += 2
        else:
            claude_args.append(arg_list[i])
            i += 1

    # in tool_use_mode, add -p (for printing mode) and --dangerously-skip-permissions
    # to make the experience smoother and avoid permission issues with the mounted vault
    if tool_use_mode:
        claude_args.append("-p")
        claude_args.append("--dangerously-skip-permissions")

    # Build env vars to bake into the cap script (these run inside the container)
    container_env = {"CLAUDE_CONFIG_DIR": "/workspace/agent/.claude"}
    if "ANTHROPIC_API_KEY" in os.environ:
        container_env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    container_env.update(env or {})

    # Build the vault snapshot (handles access filtering + CLAUDE.md injection)
    vault = Vault(ctx.fsimage, ctx.user)
    fs = ctx.fs()
    snapshot = _build_snapshot(fs, prefix, access=access, agents_md_name="CLAUDE.md")
    tmpdir = tempfile.mkdtemp(prefix="vault-claude-")
    _export_to_dir(snapshot, tmpdir)

    # Register as an active process so it shows up in top
    call_id = uuid.uuid4().hex[:8]
    prompt_summary = " ".join(claude_args)[:60] if claude_args else ""
    ctx.register_agent(call_id, f"claude: {prompt_summary}", "")

    try:
        # Run via cap's programmatic API — no subprocess needed
        result = cap_run_content(
            _build_cap_script(container_env),
            claude_args,
            cwd=tmpdir,
            interactive=ctx.interactive,
            capture=tool_use_mode,
            quiet_sync=True,
        )

        output = result.stdout + result.stderr

        if not quiet and output.strip():
            cprint(output.strip())

        # Diff and commit changes back with no-version semantics
        if readonly:
            if not quiet:
                cprint("Discarding changes (--readonly mode).")
            if tool_use_mode:
                return f"{output}\n[exit code: {result.returncode}]"
            return result.returncode == 0

        vault_prefix = (prefix.strip("/") + "/") if prefix.strip("/") else ""
        current = _diff_from_dir(tmpdir, snapshot)
        _diff_and_commit(
            vault, snapshot, current, prefix=vault_prefix, quiet=quiet,
            no_version_globs=_NO_VERSION_GLOBS,
            ignore_globs=_IGNORE_GLOBS,
            access=access,
        )

        if tool_use_mode:
            return f"{output}\n[exit code: {result.returncode}]"
        return result.returncode == 0
    except Exception as e:
        cprint(f"Error running claude: {str(e)}", file=ctx.stderr)
    finally:
        ctx.unregister_agent(call_id)
        shutil.rmtree(tmpdir, ignore_errors=True)
