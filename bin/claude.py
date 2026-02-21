import os
import shlex
from pathlib import Path

from system.context import cprint

_IMAGE = "agent-micro-os-claude"
_DOCKERFILE = Path(__file__).parent.parent / "sandboxes" / "Dockerfile.claude"
_NODE_UID = 1000

_USAGE = """\
claude - Run the Claude Code coding agent in a containerized environment with access to this workspace as /workspace.

When this command completes, the changes will be commmitted back to this workspace automatically. When the agent creates e.g. a file at /workspace/path/to/file.txt, it will be saved back to the vault at /path/to/file.txt.

When communicating to the user about what 'claude' did, always omit the /workspace prefix.

Usage: claude PROMPT
"""


async def run(*args, env: dict = None, readonly=False, quiet=False, capture=False, tool_use_mode=False):
    """Run the claude CLI in a Docker container.

    Usage: claude [--prefix PATH] [claude-args...]

    Builds the claude container image from sandboxes/Dockerfile.claude if it is
    not already present, then delegates to sandbox with the vault prefix mounted
    at /workspace as the node user (uid 1000).

    Options:
        --prefix PATH   Vault path to mount at /workspace (default: cwd)

    Args:
        *args: Remaining arguments are forwarded verbatim to the claude CLI.
        env: Optional extra environment variables for the container.
             ANTHROPIC_API_KEY is forwarded automatically when set in the host env.
        readonly: If True, do not commit changes back to the vault.
    """
    from system.context import SystemContext
    from bin.sandbox import run as sandbox_run

    ctx = SystemContext.current()
    if not ctx:
        cprint("claude: no context")
        return

    # Parse optional --prefix; everything else goes to claude
    prefix = ctx.cwd.strip("/")
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

    # Forward ANTHROPIC_API_KEY from the host environment; fix config dir
    merged_env = {}
    if "ANTHROPIC_API_KEY" in os.environ:
        merged_env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    merged_env["CLAUDE_CONFIG_DIR"] = "/workspace/agent/.claude"
    merged_env.update(env or {})

    cmd = "claude " + " ".join(shlex.quote(a) for a in claude_args) if claude_args else "claude"

    return await sandbox_run(
        "--image", _IMAGE,
        "--build", str(_DOCKERFILE),
        "--prefix", prefix,
        "--uid", str(_NODE_UID),
        # Persist only the two config files; ignore everything else in .claude/
        "--no-version", "agent/.claude/.claude.json",
        "--no-version", "agent/.claude/.credentials.json",
        "--ignore", "agent/.claude/**",
        "--cmd", cmd,
        env=merged_env,
        readonly=readonly,
        quiet=quiet,
        capture=capture,
    )
