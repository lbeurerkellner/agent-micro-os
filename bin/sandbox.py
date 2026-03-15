from system.context import cprint

# Bold grey for control messages so container output stands out
_DIM = "\033[1;90m"
_RST = "\033[0m"




async def run(*args, env: dict = None, readonly=False, quiet=False, capture=False,
              agents_md_name="AGENTS.md", access=None):
    """Launch a Docker container with vault contents mounted as a volume.

    Usage: sandbox [--image IMAGE] [--build DOCKERFILE] [--prefix PATH] [--no-version GLOB] [--cmd CMD] [path]

    Exports the current vault snapshot into a Docker volume, launches a
    container, and on exit diffs the volume back into the vault as a commit.

    Options:
        --image IMAGE       Docker image to use (default: ubuntu:24.04)
        --build DOCKERFILE  Build the image from DOCKERFILE if not already present
        --prefix PATH       Only mount files under this vault path
        --no-version GLOB   Glob pattern for paths to write back in-place (mode="a",
                            no new commit entry); may be repeated
        --cmd CMD           Run a command instead of interactive bash

    Args:
        *args: Command-line arguments as described above.
        env: Optional dict of environment variables to pass to the container.
        readonly: If True, do not commit changes back to the vault.
    """
    from system.context import SystemContext, cprint
    from fs.vault import Vault

    ctx = SystemContext.current()
    if not ctx:
        cprint(f"{_DIM}sandbox: no context{_RST}")
        return

    # Parse args
    image = "ubuntu:24.04"
    build_dockerfile = None
    prefix = ""
    cmd = None
    mount = "/workspace"
    uid = 0
    no_version_globs = []
    ignore_globs = []
    i = 0
    while i < len(args):
        if args[i] == "--image" and i + 1 < len(args):
            image = args[i + 1]
            i += 2
        elif args[i] == "--build" and i + 1 < len(args):
            build_dockerfile = args[i + 1]
            i += 2
        elif args[i] == "--prefix" and i + 1 < len(args):
            prefix = args[i + 1]
            i += 2
        elif args[i] == "--no-version" and i + 1 < len(args):
            no_version_globs.append(args[i + 1])
            i += 2
        elif args[i] == "--ignore" and i + 1 < len(args):
            ignore_globs.append(args[i + 1])
            i += 2
        elif args[i] == "--cmd" and i + 1 < len(args):
            cmd = ' '.join(args[i + 1:])
            break
        elif args[i] == "--mount" and i + 1 < len(args):
            mount = args[i + 1]
            i += 2
        elif args[i] == "--uid" and i + 1 < len(args):
            uid = int(args[i + 1])
            i += 2
        elif not args[i].startswith("--"):
            prefix = args[i]
            i += 1
        else:
            cprint(f"{_DIM}sandbox: unknown option '{args[i]}'{_RST}")
            return

    # Build image if requested and not yet present
    if build_dockerfile:
        await _ensure_image(image, build_dockerfile, quiet=quiet)

    vault = Vault(ctx.fsimage, ctx.user)
    fs = ctx.fs()

    import time as _time

    # Export (use overlay FS so provider-mounted files like /docs are included)
    snapshot = _build_snapshot(fs, prefix, access=access,
                               agents_md_name=agents_md_name)
    # Track snapshot entries that came from providers (not in the raw vault) so
    # they are excluded from diff/commit — they are read-only by definition.
    pfx = (prefix.strip("/") + "/") if prefix.strip("/") else ""
    vault_files = set(vault.list())
    provider_files = {rel for rel in snapshot if (pfx + rel) not in vault_files}

    import os
    import tempfile

    # Write vault files to a temp dir and bind-mount it into the container.
    # This avoids building a Docker image entirely — the diff is done via
    # fast local I/O after the container exits.
    tmpdir = tempfile.mkdtemp(prefix="vault-")
    _export_to_dir(snapshot, tmpdir, uid=uid, gid=uid)

    try:
        # prepare env arguments – always sync host timezone
        env = dict(env or {})
        if "TZ" not in env:
            env["TZ"] = os.environ.get("TZ") or _time.tzname[0]
        env_args = []
        for k, v in env.items():
            env_args.extend(["-e", f"{k}={v}"])

        # Launch container with bind mount
        if not quiet:
            cprint(f"{_DIM}{image}, {len(snapshot)} files{_RST}")
        tty_flags = [] if capture else ["-it"]
        docker_args = ["docker", "run", "--rm",
                        *tty_flags,
                        "-v", f"{tmpdir}:{mount}",
                        "-w", mount,
                        *env_args,
                        image]
        # Build setup preamble: workspace bin on PATH + cap stub in /tmp
        cap_stub_cmd = (
            'mkdir -p /tmp/bin && printf \'#!/bin/sh\\necho "error: cap tools cannot be called in this environment" >&2\\nexit 127\\n\''
            " > /tmp/bin/cap && chmod +x /tmp/bin/cap"
        )
        setup = f"export PATH={mount}/bin:/tmp/bin:$PATH && {cap_stub_cmd}"

        if cmd:
            docker_args.extend(["sh", "-c", f"{setup} && {cmd}"])
        else:
            docker_args.extend(["sh", "-c", f"{setup} && exec bash"])

        # Execute the container
        import asyncio
        if not capture:
            proc = await asyncio.create_subprocess_exec(*docker_args)
            exit_code = await proc.wait()
        else:
            proc = await asyncio.create_subprocess_exec(
                *docker_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            exit_code = proc.returncode
            output = stdout.decode() + stderr.decode()
            if not quiet:
                cprint(output)

        # Diff via local filesystem
        if readonly:
            if not quiet:
                cprint(f"{_DIM}Discarding changes (--readonly mode).{_RST}")
            if capture:
                return f"{output}\n[exit code: {exit_code}]"
            else:
                return exit_code == 0

        current = _diff_from_dir(tmpdir, snapshot)
        _diff_and_commit(vault, snapshot, current, prefix, quiet=quiet,
                         no_version_globs=no_version_globs,
                         ignore_globs=ignore_globs,
                         access=access,
                         provider_files=provider_files)

        if capture:
            return f"{output}\n[exit code: {exit_code}]"
        else:
            return exit_code == 0
    finally:
        # Clean up temp directory
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def _build_snapshot(fs, prefix, access=None, agents_md_name="AGENTS.md"):
    """Build a snapshot dict of {rel_path: content} from the overlay FS.

    Handles prefix scoping, access filtering, and injects AGENTS.md +
    COMMIT_MSG.  No tar is created — the dict is written directly to a
    temp directory by _export_to_dir.
    """
    from system.tools import generate_agents_md

    search_prefix = prefix.strip("/") if prefix else ""
    all_files = fs.list(prefix=search_prefix)
    if search_prefix:
        pfx = search_prefix + "/"
        files = [f for f in all_files if f.startswith(pfx)]
    else:
        pfx = ""
        files = all_files

    # Filter files by access rules
    if access:
        access_globs = [g for g, _ in access]
        files = [f for f in files if _glob_match(
            f[len(pfx):] if pfx else f, access_globs
        )]

    snapshot = {}
    for filepath in files:
        content = fs.read(filepath)
        rel = filepath[len(pfx):] if pfx else filepath
        snapshot[rel] = content

    # Inject AGENTS.md and empty COMMIT_MSG (skip for cap tool runs)
    if agents_md_name:
        md = generate_agents_md(fs, sandbox_note=True, access=access)
        snapshot[agents_md_name] = md.encode("utf-8")
        snapshot["COMMIT_MSG"] = b""

    return snapshot


def _is_executable(content: bytes) -> bool:
    """Return True if content starts with a shebang line."""
    return content.startswith(b"#!")


def _export_to_dir(snapshot, tmpdir, uid=0, gid=0):
    """Write snapshot files to a temporary directory on the host."""
    import os

    for rel, content in snapshot.items():
        path = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        os.chmod(path, 0o755 if _is_executable(content) else 0o600)


def _diff_from_dir(tmpdir, snapshot):
    """Walk the temp directory and build the current workspace state.

    Pure local I/O — no Docker API calls needed.
    """
    import os

    current = {}
    for root, _dirs, files in os.walk(tmpdir):
        for fname in files:
            full = os.path.join(root, fname)
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            rel = os.path.relpath(full, tmpdir)
            current[rel] = open(full, "rb").read()

    return current


def _glob_match(fp, globs):
    """Return True if *fp* matches any glob pattern in *globs*.

    Supports ``**`` as a recursive wildcard (matches across ``/``),
    ``*`` as a single-segment wildcard, and ``?`` for a single character.
    """
    import re

    def _to_re(pattern):
        parts = pattern.split("**")
        return ".*".join(
            re.escape(p).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
            for p in parts
        ) + "$"

    return any(re.match(_to_re(g), fp) for g in globs)


def _diff_and_commit(vault, snapshot, current, prefix, quiet=False,
                     no_version_globs=(), ignore_globs=(), access=None,
                     provider_files=None):
    provider_files = provider_files or set()
    added = set(current) - set(snapshot)
    removed = (set(snapshot) - set(current)) - provider_files
    modified = {k for k in current if k in snapshot and current[k] != snapshot[k]
                and k not in provider_files}

    vault_prefix = (prefix.strip("/") + "/") if prefix else ""

    # --no-version: write in-place (no new version row), checked before --ignore
    # so explicitly kept files are never silently dropped.
    if no_version_globs:
        for fp in (added | modified):
            if _glob_match(fp, no_version_globs):
                vault.write(vault_prefix + fp, current[fp], mode="replace")
        added = {fp for fp in added if not _glob_match(fp, no_version_globs)}
        removed = {fp for fp in removed if not _glob_match(fp, no_version_globs)}
        modified = {fp for fp in modified if not _glob_match(fp, no_version_globs)}

    # --ignore: drop everything else that matches (not written to vault at all)
    if ignore_globs:
        added = {fp for fp in added if not _glob_match(fp, ignore_globs)}
        removed = {fp for fp in removed if not _glob_match(fp, ignore_globs)}
        modified = {fp for fp in modified if not _glob_match(fp, ignore_globs)}

    # Always ignore COMMIT_MSG from versioned changes
    for s in (added, removed, modified):
        s.discard("COMMIT_MSG")

    if not added and not removed and not modified:
        if not quiet:
            cprint(f"{_DIM}No changes.{_RST}")
        return

    # Access control: validate all changes are within rw globs
    if access:
        rw_globs = [g for g, m in access if m == "rw"]
        violations = []
        for fp in added | modified | removed:
            if not _glob_match(fp, rw_globs):
                violations.append(fp)
        if violations:
            cprint(f"{_DIM}ACCESS VIOLATION: the following files are outside read-write access:")
            for fp in sorted(violations):
                cprint(f"  ! {fp}")
            cprint(f"Transaction rejected — all {len(added) + len(modified) + len(removed)} changes discarded.{_RST}")
            return

    if not quiet:
        cprint(f"{_DIM}{len(added)} added, {len(modified)} modified, {len(removed)} removed")
        # List added/modified/removed files
        for fp in sorted(added):
            cprint(f"  + {fp}")
        for fp in sorted(modified):
            cprint(f"  ~ {fp}")
        for fp in sorted(removed):
            cprint(f"  - {fp}")
        cprint(_RST, end="")

    # Use COMMIT_MSG from the agent if provided
    commit_msg_content = current.get("COMMIT_MSG", b"").strip()
    if isinstance(commit_msg_content, bytes):
        commit_msg_content = commit_msg_content.decode("utf-8", errors="replace").strip()
    if not commit_msg_content:
        commit_msg_content = f"sandbox: +{len(added)} ~{len(modified)} -{len(removed)}"

    vault.begin_commit()
    for fp in added | modified:
        vault.write(vault_prefix + fp, current[fp])
    for fp in removed:
        vault.delete(vault_prefix + fp)
    vault.end_commit(commit_msg_content)

    if not quiet:
        cprint(f"{_DIM}Committed.{_RST}")


async def _ensure_image(image, dockerfile, quiet=False):
    """Build *image* from *dockerfile* if it is not already present in Docker."""
    import asyncio
    from pathlib import Path

    import docker

    client = docker.from_env()
    try:
        client.images.get(image)
        return  # already present
    except docker.errors.ImageNotFound:
        pass

    dockerfile = Path(dockerfile)
    if not dockerfile.exists():
        raise FileNotFoundError(f"sandbox: Dockerfile not found: {dockerfile}")

    if not quiet:
        cprint(f"{_DIM}Building image {image} from {dockerfile} ...{_RST}")

    proc = await asyncio.create_subprocess_exec(
        "docker", "build", "-t", image, "-f", str(dockerfile), str(dockerfile.parent),
    )
    if await proc.wait() != 0:
        raise RuntimeError(f"sandbox: failed to build image {image}")

    if not quiet:
        cprint(f"{_DIM}Image {image} built.{_RST}")
