async def run(*args, env: dict = None, readonly=False):
    """Launch a Docker container with vault contents mounted as a volume.

    Usage: sandbox [--image IMAGE] [--prefix PATH] [--cmd CMD] [path]

    Exports the current vault snapshot into a Docker volume, launches a
    container, and on exit diffs the volume back into the vault as a commit.

    Options:
        --image IMAGE   Docker image to use (default: ubuntu:24.04)
        --prefix PATH   Only mount files under this vault path
        --cmd CMD       Run a command instead of interactive bash

    Args:
        *args: Command-line arguments as described above.
        env: Optional dict of environment variables to pass to the container.
        readonly: If True, do not commit changes back to the vault.
    """
    import subprocess
    import uuid

    import docker

    from system.context import SystemContext
    from fs.vault import Vault

    ctx = SystemContext.current()
    if not ctx:
        print("sandbox: no context")
        return

    # Parse args
    image = "ubuntu:24.04"
    prefix = ""
    cmd = None
    mount = "/workspace"
    uid = 0
    i = 0
    while i < len(args):
        if args[i] == "--image" and i + 1 < len(args):
            image = args[i + 1]
            i += 2
        elif args[i] == "--prefix" and i + 1 < len(args):
            prefix = args[i + 1]
            i += 2
        elif args[i] == "--cmd" and i + 1 < len(args):
            cmd = args[i + 1]
            i += 2
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
            print(f"sandbox: unknown option '{args[i]}'")
            return

    vault = Vault(ctx.fsimage, ctx.user)

    # Export
    tar_buf, snapshot = _export_to_tar(vault, prefix, uid=uid, gid=uid)
    print(f"Exported {len(snapshot)} files")

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

        # prepare env arguments
        env_args = []
        for k, v in (env or {}).items():
            env_args.extend(["-e", f"{k}={v}"])

        print(env_args)

        # Launch container
        print(f"Launching {image}...")
        docker_args = ["docker", "run", "--rm", "-it",
                        "-v", f"{vol_name}:{mount}", "-w", mount,
                        *env_args,
                        image]
        if cmd:
            docker_args.extend(["sh", "-c", cmd])
        else:
            docker_args.append("bash")
        subprocess.run(docker_args)

        # Diff and commit
        current = _read_volume(client, vol_name)
        if readonly:
            print("Discarding changes (--readonly mode).")
            return
        _diff_and_commit(vault, snapshot, current, prefix)
    finally:
        vol.remove()
        print(f"Volume {vol_name} removed")


def _export_to_tar(vault, prefix, uid=0, gid=0):
    import io
    import tarfile

    all_files = vault.list()
    if prefix:
        pfx = prefix.strip("/") + "/"
        files = [f for f in all_files if f.startswith(pfx)]
    else:
        pfx = ""
        files = all_files

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
            info.mode = 0o600
            info.uid = uid
            info.gid = gid
            tar.addfile(info, io.BytesIO(content))
            snapshot[rel] = content

    buf.seek(0)
    return buf, snapshot


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


def _diff_and_commit(vault, snapshot, current, prefix):
    added = set(current) - set(snapshot)
    removed = set(snapshot) - set(current)
    modified = {k for k in current if k in snapshot and current[k] != snapshot[k]}

    if not added and not removed and not modified:
        print("No changes.")
        return

    print(f"{len(added)} added, {len(modified)} modified, {len(removed)} removed")

    vault_prefix = (prefix.strip("/") + "/") if prefix else ""

    vault.begin_commit()
    for fp in added | modified:
        vault.write(vault_prefix + fp, current[fp])
    for fp in removed:
        vault.delete(vault_prefix + fp)
    vault.end_commit(f"sandbox: +{len(added)} ~{len(modified)} -{len(removed)}")
    print("Committed.")
