from pathlib import Path
import hashlib
import os

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _image_tag_for_dockerfile(dockerfile_path: Path) -> str:
    """Return an image tag that includes a hash of the Dockerfile content."""
    content = dockerfile_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()[:12]
    return f"claude-sandbox:{digest}"

DEFAULT_CONFIG = """
{
    "numStartups": 1,
    "hasCompletedOnboarding": true
}"""

async def run(*args):
    import subprocess
    import uuid
    import bin.sandbox as sandbox

    import docker

    from system.context import SystemContext
    from fs.vault import Vault

    ctx = SystemContext.current()

    # check for barebone claude configuration (also add "firstStartTime": "2026-02-07T09:49:54.448Z" and )
    claude_config_dir = ctx.read("/agent/claude/claude.json", DEFAULT_CONFIG)
    # set the minimal claude config, if it does not exist yet
    if claude_config_dir == DEFAULT_CONFIG:
        ctx.fs().write("/agent/claude/claude.json", DEFAULT_CONFIG.encode())

    # print claude code config
    print("Claude config:")
    print(claude_config_dir)
    print(ctx.fs().read("/agent/claude/claude.json").decode())
    # return

    # build <project-root>/sandboxes/Dockerfile.claude (only when Dockerfile changes)
    client = docker.from_env()
    dockerfile_path = PROJECT_ROOT / "sandboxes" / "Dockerfile.claude"
    image_name = _image_tag_for_dockerfile(dockerfile_path)
    try:
        client.images.get(image_name)
        print(f"Image {image_name} already exists, skipping build.")
    except docker.errors.ImageNotFound:
        print(f"Building {image_name}...")
        client.images.build(path=str(PROJECT_ROOT / "sandboxes"), dockerfile="Dockerfile.claude", tag=image_name)

    # fail if token is not available
    if "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ:
        print("Error: CLAUDE_CODE_OAUTH_TOKEN environment variable is not set.")
        return

    env = {
        "CLAUDE_CONFIG_DIR": "/workspace/agent/claude",
        "CLAUDE_CODE_OAUTH_TOKEN": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    }

    await sandbox.run("--image", image_name, "--cmd", "claude " + " ".join(args), "--mount", "/workspace", "--uid", "1000", env=env, readonly=False)