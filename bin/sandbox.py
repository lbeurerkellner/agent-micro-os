from system.context import cprint

# Bold grey for control messages so container output stands out
_DIM = "\033[1;90m"
_RST = "\033[0m"


_TOOL_SHEBANG_SETUP = (
    "printf '#!/bin/sh\\nif [ ! -f \"$1\" ]; then shift; fi\\nexec python3 \"$@\"\\n'"
    " > /bin/tool && chmod +x /bin/tool"
)


async def run(*args, env: dict = None, readonly=False, quiet=False, capture=False,
              agents_md_name="AGENTS.md", tool_shebang=True, access=None):
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
    import uuid

    import docker

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

    # Export (use overlay FS so provider-mounted files like /docs are included)
    tar_buf, snapshot = _export_to_tar(fs, prefix, uid=uid, gid=uid, access=access)

    # Inject dynamically generated etc/AGENTS.md into the export
    _inject_agents_md(tar_buf, snapshot, fs, uid=uid, gid=uid, filename=agents_md_name, access=access)

    # Track snapshot entries that came from providers (not in the raw vault) so
    # they are excluded from diff/commit — they are read-only by definition.
    pfx = (prefix.strip("/") + "/") if prefix.strip("/") else ""
    provider_files = {rel for rel in snapshot if not vault.exists(pfx + rel)}

    client = docker.from_env()
    vol_name = f"vault-{uuid.uuid4().hex[:12]}"
    vol = client.volumes.create(vol_name)

    try:
        # Populate volume
        temp = client.containers.create(
            "alpine", volumes={vol_name: {"bind": "/data", "mode": "rw"}}
        )
        temp.put_archive("/data", tar_buf)
        temp.remove()

        # Fix ownership of the volume root itself (put_archive doesn't chown
        # the pre-existing /data directory, only its contents)
        if uid != 0:
            client.containers.run(
                "alpine",
                command=["chown", f"{uid}:{uid}", "/data"],
                volumes={vol_name: {"bind": "/data", "mode": "rw"}},
                remove=True,
            )

        # prepare env arguments – always sync host timezone
        import os
        import time as _time
        env = dict(env or {})
        if "TZ" not in env:
            env["TZ"] = os.environ.get("TZ") or _time.tzname[0]
        env_args = []
        for k, v in env.items():
            env_args.extend(["-e", f"{k}={v}"])

        # Launch container
        if not quiet:
            cprint(f"{_DIM}{image}, {len(snapshot)} files exported{_RST}")
        tty_flags = [] if capture else ["-it"]
        docker_args = ["docker", "run", "--rm",
                        *tty_flags,
                        "-v", f"{vol_name}:{mount}", "-w", mount,
                        *env_args,
                        image]
        # Build setup preamble: workspace bin on PATH + optional /bin/tool
        setup_parts = [f"export PATH={mount}/bin:$PATH"]
        if tool_shebang:
            setup_parts.append(_TOOL_SHEBANG_SETUP)
        setup = " && ".join(setup_parts)

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

        # Diff and commit
        current = _read_volume(client, vol_name)
        if readonly:
            if not quiet:
                cprint(f"{_DIM}Discarding changes (--readonly mode).{_RST}")
            if capture:
                return f"{output}\n[exit code: {exit_code}]"
            else:
                return exit_code == 0
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
        vol.remove()


def _export_to_tar(vault, prefix, uid=0, gid=0, access=None):
    import io
    import tarfile

    search_prefix = prefix.strip("/") if prefix else ""
    all_files = vault.list(prefix=search_prefix)
    if search_prefix:
        pfx = search_prefix + "/"
        files = [f for f in all_files if f.startswith(pfx)]
    else:
        pfx = ""
        files = all_files

    # Filter files by access rules (only export files the agent is allowed to see)
    if access:
        access_globs = [g for g, _ in access]
        files = [f for f in files if _glob_match(
            f[len(pfx):] if pfx else f, access_globs
        )]

    snapshot = {}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        dirs = set()
        for filepath in files:
            rel = filepath[len(pfx):] if pfx else filepath
            parts = rel.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))
        for d in sorted(dirs):
            info = tarfile.TarInfo(name=d)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.uid = uid
            info.gid = gid
            tar.addfile(info)

        for filepath in files:
            content = vault.read(filepath)
            rel = filepath[len(pfx):] if pfx else filepath
            info = tarfile.TarInfo(name=rel)
            info.size = len(content)
            is_tool = content.startswith(b"#!/bin/tool") or content.startswith(b"#!/sbin/tool")
            info.mode = 0o755 if is_tool else 0o600
            info.uid = uid
            info.gid = gid
            tar.addfile(info, io.BytesIO(content))
            snapshot[rel] = content

    buf.seek(0)
    return buf, snapshot


def _inject_agents_md(tar_buf, snapshot, fs, uid=0, gid=0, filename="AGENTS.md", access=None):
    """Append a dynamically generated AGENTS.md to an existing tar buffer."""
    import io
    import tarfile

    from system.tools import generate_agents_md

    md = generate_agents_md(fs, sandbox_note=True, access=access)

    content = md.encode("utf-8")
    rel_path = filename

    # Reopen the tar in append mode
    tar_buf.seek(0)
    with tarfile.open(fileobj=tar_buf, mode="a") as tar:
        info = tarfile.TarInfo(name=rel_path)
        info.size = len(content)
        info.mode = 0o600
        info.uid = uid
        info.gid = gid
        tar.addfile(info, io.BytesIO(content))

        # Inject empty COMMIT_MSG file
        commit_msg = b""
        cm_info = tarfile.TarInfo(name="COMMIT_MSG")
        cm_info.size = len(commit_msg)
        cm_info.mode = 0o600
        cm_info.uid = uid
        cm_info.gid = gid
        tar.addfile(cm_info, io.BytesIO(commit_msg))

    snapshot[rel_path] = content
    snapshot["COMMIT_MSG"] = commit_msg
    tar_buf.seek(0)


def _read_volume(client, vol_name):
    import io
    import tarfile

    temp = client.containers.create(
        "alpine", volumes={vol_name: {"bind": "/data", "mode": "rw"}}
    )
    try:
        bits, _ = temp.get_archive("/data")
        buf = io.BytesIO()
        for chunk in bits:
            buf.write(chunk)
        buf.seek(0)

        current = {}
        with tarfile.open(fileobj=buf, mode="r") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                name = member.name
                if name.startswith("data/"):
                    name = name[len("data/"):]
                if name:
                    current[name] = tar.extractfile(member).read()
        return current
    finally:
        temp.remove()


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
