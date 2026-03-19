#!/usr/bin/env python3
"""🧢 cap - Run .cap.py/.cap.js/.cap.sh scripts in capability-bound Docker containers.

Commands:
  cap <script> [args...]          Run a cap script
  cap <tool-name> [args...]       Run an installed tool by name
  cap install <script>            Install a script to ~/.cap/bin/
  cap install --link <script>     Install as a symlink (live-reloads on edit)
  cap list                        List installed tools
  cap secrets list                Show all stored secrets
  cap secrets set <tool> <KEY>    Overwrite a stored secret
  cap secrets remove <tool> <KEY> Delete a stored secret
  cap --build <script> [args...]  Force-rebuild Docker images before running
  cap --verbose <script> [args...] Show Docker build output instead of spinner

Cap file format (.cap.py / .cap.js / .cap.sh):
  # ---
  # name: my-tool
  # description: What this tool does
  # dependencies: ['pypi:requests', 'npm:lodash', 'apt:ffmpeg']
  # access: ['data/**', '$@']   # files/dirs to mount into /workspace
  # network: ['api.example.com'] # outbound allowlist (or 'disable' / '*')
  # secrets: ['API_KEY']         # secrets injected as env vars at runtime
  # stateful: true               # mount a persistent volume at /root across runs
  # ---

Access: globs are relative to cwd, copied into /workspace. '$@' expands to
path args; ':ro'/':rw' suffixes control write-back (default :rw).

Network: 'disable' = no network; '*' = unrestricted; list = HTTPS proxy
allowlist (fnmatch globs or 're:...' regex). Secrets are stored in the system
keychain and injected as environment variables — never baked into the image.
"""

import ast
import fnmatch as fnmatch_module
import glob as glob_module
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# Bump when image build structure changes to invalidate cached final images.
_IMAGE_FORMAT_VERSION = "3"


@dataclass
class RunResult:
    """Result of running a cap tool."""
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _status(*args, **kwargs):
    """Print cap status/progress messages to stderr, keeping stdout clean for tool output."""
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)


import threading

class _Spinner:
    """A simple threaded spinner for long-running operations."""
    _CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, message: str):
        self._message = message
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    def _spin(self):
        i = 0
        while not self._stop.wait(0.08):
            sys.stderr.write(f"\r{self._CHARS[i % len(self._CHARS)]} {self._message}")
            sys.stderr.flush()
            i += 1

_FILTER_ADDON = """\
import fnmatch, json, os, re, time
import mitmproxy.http
from mitmproxy import ctx

_PATTERNS = %(patterns)s
_LOG_PATH = %(log_path)s

def _allowed(host):
    for p in _PATTERNS:
        if p.startswith("re:"):
            if re.search(p[3:], host):
                return True
        elif fnmatch.fnmatch(host, p):
            return True
    return False

def _log(status, method, host, path, status_code=""):
    with open(_LOG_PATH, "a") as f:
        f.write(json.dumps({
            "ts": time.time(), "status": status,
            "method": method, "host": host, "path": path,
            "code": status_code,
        }) + "\\n")

class HostFilter:
    def request(self, flow: mitmproxy.http.HTTPFlow):
        host = flow.request.pretty_host
        if not _allowed(host):
            flow.response = mitmproxy.http.Response.make(
                403, f"Blocked by cap network policy: {host}",
            )
            _log("blocked", flow.request.method, host, flow.request.path, 403)
        else:
            _log("allowed", flow.request.method, host, flow.request.path)

    def response(self, flow: mitmproxy.http.HTTPFlow):
        if flow.response and not getattr(flow, "_logged", False):
            host = flow.request.pretty_host
            _log("allowed", flow.request.method, host,
                 flow.request.path, flow.response.status_code)

addons = [HostFilter()]
"""


def parse_content(text: str, lang: str = "python"):
    """Parse cap frontmatter from a content string.

    *lang* controls the comment prefix: ``"python"``/``"sh"`` use ``#``,
    ``"js"`` uses ``//``.  Returns ``(meta, body)`` where *meta* is a dict
    of parsed fields and *body* is the remaining script text.  If no
    frontmatter block is found, *meta* still contains defaults.
    """
    lines = text.splitlines()
    prefix = "//" if lang == "js" else "#"

    def strip_comment(line):
        s = line.strip()
        if s.startswith(prefix + " "):
            return s[len(prefix) + 1:]
        if s == prefix or s == prefix + "---":
            return s[len(prefix):]
        return None  # not a comment line

    meta = {"name": None, "description": "", "dependencies": [], "lang": lang,
            "platform": None, "access": [], "network": ["*"], "secrets": [], "stateful": False,
            "user": None}

    i = 0
    if lines and lines[0].startswith("#!"):
        i = 1

    # Parse optional frontmatter between comment-prefix --- delimiters
    if i < len(lines):
        c = strip_comment(lines[i])
        if c is not None and c.strip() == "---":
            i += 1
            while i < len(lines):
                c = strip_comment(lines[i])
                if c is None:
                    break
                if c.strip() == "---":
                    i += 1
                    break
                if ":" in c:
                    key, _, val = c.partition(":")
                    key, val = key.strip(), val.strip()
                    if key == "name":
                        meta["name"] = val
                    elif key == "description":
                        meta["description"] = val
                    elif key == "dependencies":
                        try:
                            meta["dependencies"] = ast.literal_eval(val)
                        except Exception:
                            meta["dependencies"] = []
                    elif key == "platform":
                        meta["platform"] = val
                    elif key == "access":
                        try:
                            meta["access"] = ast.literal_eval(val)
                        except Exception:
                            meta["access"] = []
                    elif key == "network":
                        stripped = val.strip("'\"")
                        if stripped == "disable":
                            meta["network"] = "disable"
                        elif stripped == "*":
                            meta["network"] = ["*"]
                        else:
                            try:
                                meta["network"] = ast.literal_eval(val)
                            except Exception:
                                meta["network"] = "*"
                    elif key == "secrets":
                        try:
                            meta["secrets"] = ast.literal_eval(val)
                        except Exception:
                            meta["secrets"] = []
                    elif key == "stateful":
                        meta["stateful"] = val.strip().lower() in ("true", "yes", "1")
                    elif key == "user":
                        meta["user"] = val.strip().strip("'\"")
                    elif key == "runtime":
                        rt = val.strip().strip("'\"").lower()
                        runtime_map = {"python": "python", "node": "js", "shell": "sh", "sh": "sh", "js": "js"}
                        if rt in runtime_map:
                            meta["lang"] = runtime_map[rt]
                i += 1

    body = "\n".join(lines[i:]).strip()
    return meta, body


def parse_file(path: str):
    """Parse a .cap.{py,js,sh} file into (meta, body).

    Strips the shebang and frontmatter block; returns the raw script body.
    """
    text = Path(path).read_text()
    lang = "js" if path.endswith(".js") else "sh" if path.endswith(".sh") else "python"

    meta, body = parse_content(text, lang=lang)

    if not meta["name"]:
        name = Path(path).name
        for suf in (".cap.py", ".cap.js", ".cap.sh", ".cap"):
            if name.endswith(suf):
                meta["name"] = name[: -len(suf)]
                break
        else:
            meta["name"] = name.split(".")[0]

    return meta, body


def compute_hashes(dependencies: list, body: str, platform: str = None, ca_cert_hash: str = None,
                   secrets: list = None, user: str = None):
    deps_str = repr(sorted(dependencies)) + "\n" + (platform or "") + "\n" + (ca_cert_hash or "") + "\n" + (user or "")
    deps_hash = hashlib.sha256(deps_str.encode()).hexdigest()[:12]
    secrets_str = repr(sorted(secrets or []))
    full_str = deps_str + "\n" + body + "\n" + secrets_str + "\n" + _IMAGE_FORMAT_VERSION
    full_hash = hashlib.sha256(full_str.encode()).hexdigest()[:12]
    return deps_hash, full_hash


def image_exists(tag: str) -> bool:
    r = subprocess.run(["docker", "images", "-q", tag], capture_output=True, text=True)
    return bool(r.stdout.strip())


def build_deps_image(name: str, dependencies: list, tag: str, platform: str = None,
                     ca_cert_path: str = None, user: str = None, verbose: bool = False):
    _VALID_PREFIXES = ("pypi:", "npm:", "apt:")
    unknown = [d for d in dependencies if not any(d.startswith(p) for p in _VALID_PREFIXES)]
    if unknown:
        raise ValueError(f"cap: unsupported dependency type '{unknown}'  (supported: {', '.join(_VALID_PREFIXES)})")

    apt = [d[4:] for d in dependencies if d.startswith("apt:")]
    pypi = [d[5:] for d in dependencies if d.startswith("pypi:")]
    npm = [d[4:] for d in dependencies if d.startswith("npm:")]

    dockerfile_lines = [
        "FROM python:3.12-slim",
        # Install uv + current Node.js LTS in one layer
        "RUN apt-get update && apt-get install -y curl ca-certificates && \\",
        "    curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \\",
        "    apt-get install -y nodejs && \\",
        "    pip install uv --no-cache-dir && \\",
        "    rm -rf /var/lib/apt/lists/*",
        "WORKDIR /app",
        "RUN uv venv /venv",
        'ENV PATH="/venv/bin:$PATH" VIRTUAL_ENV=/venv',
    ]
    # Create a non-root user when user is specified
    if user:
        dockerfile_lines.append(
            f'RUN useradd -m -u {user} -s /bin/sh capuser'
        )
    if apt:
        dockerfile_lines.append(
            f'RUN apt-get update && apt-get install -y --no-install-recommends {" ".join(apt)} && rm -rf /var/lib/apt/lists/*'
        )
    if pypi:
        dockerfile_lines.append(f'RUN uv pip install {" ".join(pypi)}')
    if npm:
        dockerfile_lines.append(f'RUN npm install -g {" ".join(npm)}')
    if ca_cert_path:
        dockerfile_lines.extend([
            "COPY cap-ca.crt /usr/local/share/ca-certificates/cap-ca.crt",
            "RUN update-ca-certificates",
            'ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt',
            'ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt',
            'ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt',
            'ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt',
        ])

    dockerfile = "\n".join(dockerfile_lines) + "\n"
    platform_args = ["--platform", platform] if platform else []
    capture = {} if verbose else {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if verbose:
        _status(f"Building deps image {tag} ...")
    if ca_cert_path:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "Dockerfile").write_text(dockerfile)
            shutil.copy2(ca_cert_path, os.path.join(tmp, "cap-ca.crt"))
            if verbose:
                subprocess.run(["docker", "build", *platform_args, "-t", tag, tmp], check=True)
            else:
                with _Spinner("Installing dependencies..."):
                    subprocess.run(["docker", "build", *platform_args, "-t", tag, tmp],
                                   check=True, **capture)
    else:
        if verbose:
            subprocess.run(
                ["docker", "build", *platform_args, "-t", tag, "-"],
                input=dockerfile.encode(), check=True,
            )
        else:
            with _Spinner("Installing dependencies..."):
                subprocess.run(
                    ["docker", "build", *platform_args, "-t", tag, "-"],
                    input=dockerfile.encode(), check=True, **capture,
                )


def build_final_image(deps_tag: str, body: str, lang: str, tag: str, platform: str = None,
                      verbose: bool = False, user: str = None):
    if lang == "python":
        script_file = "cli.py"
        run_cmd = "python3 /app/cli.py"
        extra_layers = ""
    elif lang == "js":
        script_file = "cli.js"
        run_cmd = "node /app/cli.js"
        extra_layers = ""
    else:  # sh
        script_file = "cli.sh"
        run_cmd = "/bin/sh /app/cli.sh"
        extra_layers = "RUN chmod +x /app/cli.sh\n"

    if user:
        # Entrypoint wrapper: start as root, fix workspace ownership,
        # then drop to the target user.  This is needed because the
        # bind-mounted workspace is owned by the host UID (usually 0)
        # and tools like Claude Code refuse config files owned by
        # a different user.
        entrypoint_sh = (
            "#!/bin/sh\n"
            f"chown -R {user}:{user} /workspace 2>/dev/null\n"
            f"exec su -s /bin/sh capuser -c '{run_cmd} \"$@\"' -- \"$@\"\n"
        )
        extra_layers += "COPY entrypoint.sh /app/entrypoint.sh\nRUN chmod +x /app/entrypoint.sh\n"
        entrypoint = '["/app/entrypoint.sh"]'
    else:
        entrypoint_sh = None
        parts = ", ".join('"' + w + '"' for w in run_cmd.split())
        entrypoint = f'[{parts}]'

    dockerfile = (
        f"FROM {deps_tag}\n"
        f"COPY {script_file} /app/{script_file}\n"
        f"{extra_layers}"
        f"ENTRYPOINT {entrypoint}\n"
    )
    platform_args = ["--platform", platform] if platform else []
    capture = {} if verbose else {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, script_file).write_text(body)
        if entrypoint_sh:
            Path(tmp, "entrypoint.sh").write_text(entrypoint_sh)
        Path(tmp, "Dockerfile").write_text(dockerfile)
        if verbose:
            _status(f"Building final image {tag} ...")
            subprocess.run(["docker", "build", *platform_args, "-t", tag, tmp], check=True)
        else:
            with _Spinner("Preparing sandbox..."):
                subprocess.run(["docker", "build", *platform_args, "-t", tag, tmp],
                               check=True, **capture)


def _file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_rw(entry):
    """Return True if an access entry is read-write (default when no suffix)."""
    if entry.endswith(":ro"):
        return False
    return True  # :rw or no suffix → rw


def _glob_match_path(path, pattern):
    """Match a path against a glob pattern with ** support.

    ``**/`` is treated as zero-or-more directory segments so that
    ``dir/**/*`` matches both ``dir/file`` and ``dir/sub/file``.
    """
    import re as _re
    escaped = _re.escape(pattern)
    # Order matters: handle **/ before lone **
    escaped = escaped.replace(r"\*\*/", "(.*/)?")
    escaped = escaped.replace(r"\*\*", ".*")
    escaped = escaped.replace(r"\*", "[^/]*")
    escaped = escaped.replace(r"\?", "[^/]")
    return bool(_re.match(escaped + "$", path))


def build_workspace(access: list, extra_args: list, cwd: str):
    """Collect files into a tmpdir to mount as /workspace.

    Each entry in access is a glob pattern (relative to cwd) with an optional
    ':ro'/':rw' suffix. '$@' expands to extra_args that are valid paths.

    Returns (tmpdir, container_args, ws_info) where:
      - container_args has $@ path args remapped to /workspace equivalents
      - ws_info is a dict with keys: file_map, rw_rels, hashes (or None)
    """
    # Always create /workspace so it exists in the container regardless of access patterns
    tmpdir = tempfile.mkdtemp(prefix="cap-ws-")

    if not access:
        return tmpdir, list(extra_args), None

    # Expand $@ to path args from extra_args
    path_args = {arg: None for arg in extra_args
                 if not arg.startswith("-") and os.path.exists(arg)}

    # Determine the mode (:ro/:rw) for each access entry.
    # Collect {dest_rel: src_abs} for all matched files, tracking rw status.
    files = {}      # rel -> abs source path
    rw_rels = set() # rel paths that are writable
    rw_globs = []   # raw rw glob patterns (for matching new files at sync time)

    for entry in access:
        writable = _is_rw(entry)

        if entry.startswith("$@"):
            patterns = list(path_args.keys())
            if writable:
                rw_globs.extend(patterns)
        else:
            raw = entry
            if raw.endswith((":ro", ":rw")):
                raw = raw[:-3]
            patterns = [raw]
            if writable:
                rw_globs.append(raw)
                # If the pattern has no glob chars, also allow files
                # beneath it so that directory paths like "var/experiences"
                # implicitly cover "var/experiences/**".
                if "*" not in raw and "?" not in raw:
                    rw_globs.append(raw.rstrip("/") + "/**")

        for pattern in patterns:
            abs_pattern = pattern if os.path.isabs(pattern) else os.path.join(cwd, pattern)
            matches = glob_module.glob(abs_pattern, recursive=True)
            if not matches and os.path.exists(abs_pattern):
                matches = [abs_pattern]
            for match in matches:
                match = os.path.normpath(match)
                if os.path.isfile(match):
                    rel = os.path.relpath(match, cwd)
                    if rel.startswith(".."):
                        rel = os.path.basename(match)
                    files[rel] = match
                    if writable:
                        rw_rels.add(rel)
                elif os.path.isdir(match):
                    for root, _, fnames in os.walk(match):
                        for fname in fnames:
                            full = os.path.join(root, fname)
                            rel = os.path.relpath(full, cwd)
                            if rel.startswith(".."):
                                rel = os.path.join(
                                    os.path.basename(match),
                                    os.path.relpath(full, match),
                                )
                            files[rel] = full
                            if writable:
                                rw_rels.add(rel)

    hashes = {}
    for rel, src in files.items():
        dst = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        hashes[rel] = _file_hash(src)

    # Remap $@ path args to /workspace/<rel> for the container
    def remap(arg):
        if arg not in path_args:
            return arg
        abs_arg = arg if os.path.isabs(arg) else os.path.join(cwd, arg)
        abs_arg = os.path.normpath(abs_arg)
        rel = os.path.relpath(abs_arg, cwd)
        if rel.startswith(".."):
            rel = os.path.basename(arg)
        return f"/workspace/{rel}"

    container_args = [remap(a) for a in extra_args]
    ws_info = {"file_map": files, "rw_rels": rw_rels, "rw_globs": rw_globs, "hashes": hashes}
    return tmpdir, container_args, ws_info


def sync_workspace(tmpdir, ws_info, cwd, quiet=False):
    """Diff the workspace after the container exits and write back :rw changes.

    Prints a summary of all changes. Only :rw files are written back;
    :ro changes are reported as discarded.
    """
    file_map = ws_info["file_map"]
    rw_rels = ws_info["rw_rels"]
    rw_globs = ws_info.get("rw_globs", [])
    orig_hashes = ws_info["hashes"]

    # Scan current state of the workspace tmpdir
    current = {}
    for root, _, fnames in os.walk(tmpdir):
        for fname in fnames:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, tmpdir)
            current[rel] = _file_hash(full)

    added = sorted(set(current) - set(orig_hashes))
    removed = sorted(set(orig_hashes) - set(current))
    modified = sorted(
        rel for rel in current
        if rel in orig_hashes and current[rel] != orig_hashes[rel]
    )

    if not added and not removed and not modified:
        return

    # Classify changes
    written = []
    discarded = []

    def _matches_rw(rel):
        """Check if rel matches any rw_rels entry or rw_globs pattern."""
        if rel in rw_rels:
            return True
        for p in rw_rels:
            target = os.path.relpath(p, cwd) if os.path.isabs(p) else p
            if fnmatch_module.fnmatch(rel, target):
                return True
        for pattern in rw_globs:
            if fnmatch_module.fnmatch(rel, pattern):
                return True
            if "**" in pattern:
                if _glob_match_path(rel, pattern):
                    return True
        return False

    for rel in added:
        if _matches_rw(rel):
            dst = os.path.join(cwd, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(tmpdir, rel), dst)
            written.append(("+ ", rel))
        else:
            discarded.append(("+ ", rel))

    for rel in modified:
        if rel in rw_rels:
            dst = file_map[rel]
            shutil.copy2(os.path.join(tmpdir, rel), dst)
            written.append(("~ ", rel))
        else:
            discarded.append(("~ ", rel))

    for rel in removed:
        if rel in rw_rels:
            dst = file_map[rel]
            if os.path.exists(dst):
                os.unlink(dst)
            written.append(("- ", rel))
        else:
            discarded.append(("- ", rel))

    # Print summary
    if not quiet:
        if written:
            _status("File Changes:")
            for prefix, rel in written:
                color = {"+ ": "32", "~ ": "33", "- ": "31"}[prefix]
                _status(f"  \033[{color}m{prefix}{rel}\033[0m")

        if discarded:
            _status("\n\033[1;90mDiscarded (read-only):\033[0m")
            for prefix, rel in discarded:
                _status(f"  \033[90m{prefix}{rel}\033[0m")


# ---------------------------------------------------------------------------
# Network policy helpers
# ---------------------------------------------------------------------------

def ensure_ca():
    """Return (confdir, cert_path), generating a CA keypair on first use."""
    ca_dir = Path.home() / ".cap" / "proxy"
    ca_key = ca_dir / "ca.key"
    ca_cert = ca_dir / "ca-cert.pem"
    ca_pem = ca_dir / "mitmproxy-ca.pem"

    if ca_pem.exists() and ca_cert.exists():
        return ca_dir, ca_cert

    ca_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(ca_key),
            "-out", str(ca_cert),
            "-days", "3650",
            "-subj", "/CN=cap proxy CA",
        ],
        check=True,
        capture_output=True,
    )
    # mitmproxy expects combined key+cert in mitmproxy-ca.pem
    ca_pem.write_text(ca_key.read_text() + ca_cert.read_text())
    return ca_dir, ca_cert


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_filter_addon(patterns):
    """Write a mitmdump addon that allowlists the given host patterns.

    Returns (addon_path, log_path).
    """
    fd_log, log_path = tempfile.mkstemp(prefix="cap-netlog-", suffix=".jsonl")
    os.close(fd_log)
    content = _FILTER_ADDON % {
        "patterns": json.dumps(patterns),
        "log_path": json.dumps(log_path),
    }
    fd, addon_path = tempfile.mkstemp(prefix="cap-filter-", suffix=".py")
    os.write(fd, content.encode())
    os.close(fd)
    return addon_path, log_path


def start_proxy(ca_dir, patterns=None):
    """Start mitmdump with the cap CA; return (port, Popen, tmpfiles, log_path)."""
    if shutil.which("mitmdump") is None:
        print(
            "cap: network allowlists require mitmproxy.\n"
            "Install it with:  pip install mitmproxy",
            file=sys.stderr,
        )
        sys.exit(1)

    port = _find_free_port()
    tmpfiles = []
    log_path = None

    cmd = [
        "mitmdump",
        "--listen-port", str(port),
        "--set", f"confdir={ca_dir}",
    ]

    if patterns:
        addon_path, log_path = _write_filter_addon(patterns)
        tmpfiles.extend([addon_path, log_path])
        cmd.extend(["-s", addon_path])

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=sys.stderr)

    # Wait for the proxy to accept connections
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError(f"mitmdump failed to start on port {port}")

    return port, proc, tmpfiles, log_path


def print_network_log(log_path):
    """Read the proxy log and print a summary of hosts contacted."""
    if not log_path or not os.path.exists(log_path):
        return

    entries = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    if not entries:
        return

    # Group by host, track allowed/blocked and methods
    hosts = {}
    for e in entries:
        host = e["host"]
        if host not in hosts:
            hosts[host] = {"allowed": 0, "blocked": 0, "methods": set()}
        hosts[host][e["status"]] = hosts[host].get(e["status"], 0) + 1
        hosts[host]["methods"].add(e["method"])

    _status("\n\033[1mNetwork connections:\033[0m")
    for host in sorted(hosts):
        info = hosts[host]
        allowed = info.get("allowed", 0)
        blocked = info.get("blocked", 0)
        methods = ", ".join(sorted(info["methods"]))

        if blocked and not allowed:
            color = "31"  # red — fully blocked
            status = "blocked"
        elif blocked:
            color = "33"  # yellow — partially blocked
            status = f"{allowed} allowed, {blocked} blocked"
        else:
            color = "32"  # green — all allowed
            status = f"{allowed} req"

        _status(f"  \033[{color}m{host}\033[0m  {methods}  ({status})")


# ---------------------------------------------------------------------------
# Secret management (keyring-backed)
# ---------------------------------------------------------------------------

def _secrets_registry_path():
    return Path.home() / ".cap" / "secrets_registry.json"


def _load_secrets_registry() -> dict:
    path = _secrets_registry_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def _save_secrets_registry(registry: dict):
    path = _secrets_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2))


def resolve_secrets(name: str, full_hash: str, secret_names: list,
                    script_path: str = None) -> dict:
    """Return {SECRET_NAME: value} for all secrets required by this cap version.

    On first use, prompts the user for each secret value and stores it in the
    system keychain via the ``keyring`` library.  When the cap file changes
    (new full_hash), the user is asked to re-authorise access before the
    previously stored value is copied to the new version slot.
    """
    if not secret_names:
        return {}

    try:
        import keyring  # noqa: PLC0415
    except ImportError:
        print(
            "cap: secrets require the 'keyring' package.\n"
            "Install with: pip install keyring",
            file=sys.stderr,
        )
        sys.exit(1)

    import getpass

    registry = _load_secrets_registry()
    resolved = {}

    for secret_name in secret_names:
        registry_key = f"{name}:{secret_name}"
        service = "cap"
        username = f"{name}:{full_hash}:{secret_name}"

        # Happy path: secret already stored for this exact cap version.
        value = keyring.get_password(service, username)
        if value is not None:
            resolved[secret_name] = value
            continue

        # Check whether a secret was stored for a previous version of this cap.
        prev_hash = registry.get(registry_key)
        prev_value = None
        if prev_hash and prev_hash != full_hash:
            prev_value = keyring.get_password(service, f"{name}:{prev_hash}:{secret_name}")

        if prev_value is not None:
            _status(f"\ncap: '{name}' has changed. Re-authorise secret access?")
            if script_path and os.path.isfile(script_path):
                _status(f"\n--- {script_path} ---")
                _status(Path(script_path).read_text().rstrip())
                _status(f"--- end of {os.path.basename(script_path)} ---\n")
            _status(f"  Secret : {secret_name}")
            _status(f"  Old ver: {prev_hash}  →  New ver: {full_hash}")
            ans = input("  Grant to new version? [Y/n] ").strip().lower()
            if ans in ("", "y", "yes"):
                value = prev_value
            else:
                print(f"cap: access to {secret_name} denied for new version.", file=sys.stderr)
                sys.exit(1)
        else:
            # First time — ask the user for the secret.
            _status(f"\ncap: '{name}' requires secret '{secret_name}'")
            value = getpass.getpass(f"  Enter value for {secret_name}: ")
            if not value:
                print(f"cap: no value provided for {secret_name}.", file=sys.stderr)
                sys.exit(1)

        # Persist the secret and update the registry.
        keyring.set_password(service, username, value)
        registry[registry_key] = full_hash
        _save_secrets_registry(registry)
        resolved[secret_name] = value

    return resolved


def _cmd_list():
    """List all tools installed in ~/.cap/bin/."""
    bin_dir = Path.home() / ".cap" / "bin"
    if not bin_dir.is_dir():
        print("No tools installed (~/.cap/bin/ does not exist).")
        return

    entries = []
    for p in sorted(bin_dir.iterdir()):
        if not (p.is_file() or p.is_symlink()):
            continue
        name = p.name
        # Accept .cap.py / .cap.js, or any file without a doc extension
        is_cap = name.endswith(".cap.py") or name.endswith(".cap.js") or name.endswith(".cap.sh")
        is_doc = p.suffix in (".md", ".txt", ".rst")
        if not is_cap and is_doc:
            continue
        try:
            meta, _ = parse_file(str(p))
            entries.append((meta["name"], meta.get("description", "")))
        except Exception:
            entries.append((p.name, ""))

    if not entries:
        print("No tools installed in ~/.cap/bin/.")
        return

    name_width = max(len(n) for n, _ in entries)
    for name, desc in entries:
        if desc:
            print(f"  {name:<{name_width}}  {desc}")
        else:
            print(f"  {name}")


def _cmd_install(script_path: str, link: bool = False):
    """Copy (or link) a .cap.py/.cap.js file into ~/.cap/bin/."""
    src = Path(script_path).expanduser().resolve()
    if not src.is_file():
        print(f"cap: file not found: {script_path}", file=sys.stderr)
        sys.exit(1)
    bin_dir = Path.home() / ".cap" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    dst = bin_dir / src.name
    if link:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
    else:
        shutil.copy2(src, dst)
        dst.chmod(dst.stat().st_mode | 0o755)
    meta, _ = parse_file(str(dst))
    verb = "Linked" if link else "Installed"
    print(f"{verb} {meta['name']} → {dst}")


def _cmd_secrets(sub_args: list):
    """Manage stored secrets: list, remove, set.

    cap secrets list
    cap secrets remove <tool-name> <SECRET_NAME>
    cap secrets set   <tool-name> <SECRET_NAME>
    """
    try:
        import keyring  # noqa: PLC0415
    except ImportError:
        print(
            "cap: secrets require the 'keyring' package.\n"
            "Install with: pip install keyring",
            file=sys.stderr,
        )
        sys.exit(1)

    usage = (
        "Usage:\n"
        "  cap secrets list\n"
        "  cap secrets remove <tool-name> <SECRET_NAME>\n"
        "  cap secrets set    <tool-name> <SECRET_NAME>"
    )

    if not sub_args or sub_args[0] in ("-h", "--help"):
        print(usage)
        sys.exit(0)

    action = sub_args[0]

    if action == "list":
        registry = _load_secrets_registry()
        if not registry:
            print("No secrets stored.")
            return
        # Determine column widths
        tool_w = max(len(k.split(":")[0]) for k in registry)
        sec_w  = max(len(k.split(":")[1]) for k in registry)
        print(f"  {'TOOL':<{tool_w}}  {'SECRET':<{sec_w}}  VERSION")
        print(f"  {'-'*tool_w}  {'-'*sec_w}  {'-------'}")
        for reg_key, stored_hash in sorted(registry.items()):
            tool_name, secret_name = reg_key.split(":", 1)
            username = f"{tool_name}:{stored_hash}:{secret_name}"
            exists = keyring.get_password("cap", username) is not None
            flag = "" if exists else "  \033[33m(value missing from keychain)\033[0m"
            print(f"  {tool_name:<{tool_w}}  {secret_name:<{sec_w}}  {stored_hash[:12]}{flag}")
        return

    if action == "remove":
        if len(sub_args) < 3:
            print(usage, file=sys.stderr)
            sys.exit(1)
        tool_name, secret_name = sub_args[1], sub_args[2]
        registry = _load_secrets_registry()
        reg_key = f"{tool_name}:{secret_name}"
        stored_hash = registry.get(reg_key)
        if stored_hash:
            username = f"{tool_name}:{stored_hash}:{secret_name}"
            try:
                keyring.delete_password("cap", username)
            except keyring.errors.PasswordDeleteError:
                pass
            del registry[reg_key]
            _save_secrets_registry(registry)
            print(f"Removed {secret_name} for tool '{tool_name}'.")
        else:
            print(f"cap: no stored secret '{secret_name}' for tool '{tool_name}'.", file=sys.stderr)
            sys.exit(1)
        return

    if action == "set":
        if len(sub_args) < 3:
            print(usage, file=sys.stderr)
            sys.exit(1)
        import getpass
        tool_name, secret_name = sub_args[1], sub_args[2]
        registry = _load_secrets_registry()
        reg_key = f"{tool_name}:{secret_name}"
        stored_hash = registry.get(reg_key)
        if not stored_hash:
            print(
                f"cap: no registry entry for '{secret_name}' / tool '{tool_name}'.\n"
                "Run the cap tool once so it can register the secret first.",
                file=sys.stderr,
            )
            sys.exit(1)
        value = getpass.getpass(f"New value for {secret_name}: ")
        if not value:
            print("cap: empty value not stored.", file=sys.stderr)
            sys.exit(1)
        username = f"{tool_name}:{stored_hash}:{secret_name}"
        keyring.set_password("cap", username, value)
        print(f"Updated {secret_name} for tool '{tool_name}' (version {stored_hash[:12]}).")
        return

    print(f"cap secrets: unknown action '{action}'.\n\n{usage}", file=sys.stderr)
    sys.exit(1)


def _run_tool(meta, body, extra_args, *, cwd=None, force_build=False,
              verbose=False, quiet_sync=False, interactive=None,
              capture=False, script_path=None):
    """Core logic for running a cap tool. Returns a RunResult.

    This is the shared implementation for the programmatic API and the CLI.

    Args:
        meta: Parsed frontmatter dict.
        body: Script body text.
        extra_args: Arguments to pass to the tool.
        cwd: Working directory for workspace resolution (default: os.getcwd()).
        force_build: Force-rebuild Docker images.
        verbose: Show Docker build output instead of spinner.
        quiet_sync: Suppress workspace sync output.
        interactive: If True, inherit terminal for docker run. If False,
            capture stdout/stderr. None auto-detects from tty.
        capture: If True, capture docker run stdout/stderr into RunResult.
            Ignored when interactive=True.
        script_path: Path to the original script file (for secret prompts).
    """
    name = meta["name"]
    lang = meta["lang"]
    deps = meta["dependencies"]
    platform = meta["platform"]
    access = meta["access"]
    network = meta["network"]
    secrets = meta["secrets"]
    user = meta.get("user")
    cwd = cwd or os.getcwd()

    # --- Image build -------------------------------------------------------
    ca_cert_path = None
    if isinstance(network, list):
        _, ca_cert_path = ensure_ca()

    ca_cert_hash = _file_hash(ca_cert_path) if ca_cert_path else None
    deps_hash, full_hash = compute_hashes(deps, body, platform=platform,
                                          ca_cert_hash=ca_cert_hash, secrets=secrets,
                                          user=user)
    deps_tag = f"cap-{name}-deps:{deps_hash}"
    final_tag = f"cap-{name}:{full_hash}"

    if force_build or not image_exists(final_tag):
        if force_build or not image_exists(deps_tag):
            build_deps_image(name, deps, deps_tag, platform=platform, ca_cert_path=ca_cert_path,
                             user=user, verbose=verbose)
        build_final_image(deps_tag, body, lang, final_tag, platform=platform, verbose=verbose,
                          user=user)

    # --- Secrets -----------------------------------------------------------
    secret_values = resolve_secrets(name, full_hash, secrets, script_path=script_path)
    secret_env_args = [arg for k, v in secret_values.items() for arg in ("-e", f"{k}={v}")]

    # --- Workspace ---------------------------------------------------------
    workspace_tmp, container_args, ws_info = build_workspace(access, extra_args or [], cwd)

    # --- Network policy ----------------------------------------------------
    proxy_proc = None
    proxy_tmpfiles = []
    network_args = []
    net_log_path = None

    if network == "disable":
        network_args = ["--network", "none"]
    elif isinstance(network, list):
        ca_dir, _ = ensure_ca()
        port, proxy_proc, proxy_tmpfiles, net_log_path = start_proxy(ca_dir, patterns=network)
        proxy_url = f"http://host.docker.internal:{port}"
        network_args = [
            "--add-host", "host.docker.internal:host-gateway",
            "-e", f"HTTP_PROXY={proxy_url}",
            "-e", f"HTTPS_PROXY={proxy_url}",
            "-e", f"http_proxy={proxy_url}",
            "-e", f"https_proxy={proxy_url}",
        ]

    # --- Docker run --------------------------------------------------------
    if interactive is None:
        interactive = sys.stdin.isatty()

    tty = ["-it"] if interactive else ["-i"]
    platform_args = ["--platform", platform] if platform else []
    workspace_mount = ["-v", f"{workspace_tmp}:/workspace"]
    home_dir = "/home/capuser" if user else "/root"
    home_volume_args = ["-v", f"cap-{name}-home:{home_dir}"] if meta["stateful"] else []
    # When user is set, the entrypoint wrapper starts as root to chown
    # /workspace, then drops to the target user — no --user flag needed.
    user_args = []

    docker_cmd = [
        "docker", "run", "--rm", *tty, *platform_args,
        *user_args,
        *workspace_mount, *home_volume_args, "-w", "/workspace", *network_args,
        *secret_env_args, final_tag, *container_args,
    ]

    try:
        if capture and not interactive:
            result = subprocess.run(docker_cmd, capture_output=True)
        else:
            result = subprocess.run(docker_cmd)

        if workspace_tmp and ws_info:
            sync_workspace(workspace_tmp, ws_info, cwd, quiet=quiet_sync)
        if net_log_path:
            print_network_log(net_log_path)

        return RunResult(
            returncode=result.returncode,
            stdout=result.stdout.decode() if result.stdout else "",
            stderr=result.stderr.decode() if result.stderr else "",
        )
    finally:
        if workspace_tmp:
            shutil.rmtree(workspace_tmp, ignore_errors=True)
        if proxy_proc:
            proxy_proc.terminate()
            proxy_proc.wait(timeout=5)
        for f in proxy_tmpfiles:
            os.unlink(f)


# ---------------------------------------------------------------------------
# Programmatic API
# ---------------------------------------------------------------------------

def run(script_path: str, extra_args: list = None, **kwargs) -> RunResult:
    """Run a cap tool from a script file.

    Returns a RunResult with returncode, stdout, and stderr.
    Keyword arguments are forwarded to ``_run_tool`` (see its docstring
    for ``cwd``, ``force_build``, ``verbose``, ``interactive``, ``capture``,
    ``quiet_sync``).
    """
    meta, body = parse_file(script_path)
    kwargs.setdefault("script_path", script_path)
    return _run_tool(meta, body, extra_args, **kwargs)


def run_script(content: str, extra_args: list = None, *,
                name: str = None, lang: str = None, **kwargs) -> RunResult:
    """Run a cap tool from inline script content (no file on disk needed).

    The *content* string should include the frontmatter block.  An optional
    *name* overrides the tool name (used for image tags and stateful volumes).
    *lang* overrides language detection (``"python"``, ``"js"``, ``"sh"``).

    Returns a RunResult with returncode, stdout, and stderr.
    Keyword arguments are forwarded to ``_run_tool``.
    """
    detected_lang = lang or ("js" if content.lstrip().startswith("//") else
                             "sh" if "runtime: shell" in content or "runtime: sh" in content
                             else "python")
    meta, body = parse_content(content, lang=detected_lang)
    if name:
        meta["name"] = name
    if not meta["name"]:
        meta["name"] = "inline-tool"
    return _run_tool(meta, body, extra_args, **kwargs)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    force_build = False
    quiet_sync = False
    verbose = False
    args = list(argv)
    while args and args[0].startswith("--"):
        if args[0] == "--build":
            force_build = True
            args = args[1:]
        elif args[0] == "--quiet":
            quiet_sync = True
            args = args[1:]
        elif args[0] == "--verbose":
            verbose = True
            args = args[1:]
        else:
            break

    if not args:
        print(__doc__)
        sys.exit(0)

    # Built-in commands
    if args[0] == "list":
        _cmd_list()
        sys.exit(0)

    if args[0] == "secrets":
        _cmd_secrets(args[1:])
        sys.exit(0)

    if args[0] == "install":
        if len(args) < 2:
            print("Usage: cap install [--link] <script.cap.py|.cap.js|.cap.sh>", file=sys.stderr)
            sys.exit(1)
        link = False
        install_args = args[1:]
        if install_args and install_args[0] == "--link":
            link = True
            install_args = install_args[1:]
        if not install_args:
            print("Usage: cap install [--link] <script.cap.py|.cap.js|.cap.sh>", file=sys.stderr)
            sys.exit(1)
        _cmd_install(install_args[0], link=link)
        sys.exit(0)

    script_path = args[0]
    extra_args = args[1:]

    if not os.path.exists(script_path):
        bin_dir = Path.home() / ".cap" / "bin"
        name = script_path
        candidates = [
            bin_dir / name,
            bin_dir / f"{name}.cap.py",
            bin_dir / f"{name}.cap.js",
            bin_dir / f"{name}.cap.sh",
        ]
        resolved = next((str(c) for c in candidates if c.is_file()), None)
        if resolved is None:
            print(f"cap: file not found: {script_path}", file=sys.stderr)
            sys.exit(1)
        script_path = resolved

    result = run(script_path, extra_args, force_build=force_build,
                 verbose=verbose, quiet_sync=quiet_sync)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
