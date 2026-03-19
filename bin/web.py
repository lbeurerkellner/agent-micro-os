"""Minimal FastAPI web UI for browsing vault filesystem contents."""

import argparse
import html as html_mod
import secrets
import sys
from pathlib import Path

import bcrypt

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fs.vault import Vault

app = FastAPI()

# Populated at startup from CLI args
FSIMAGE: str = ""
PASSWD: dict[str, str] = {}  # user -> password
SESSIONS: dict[str, str] = {}  # token -> user


def load_passwd(path: str) -> dict[str, str]:
    """Load user:password pairs from a passwd file (one per line)."""
    users = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            user, _, pw = line.partition(":")
            if user and pw:
                users[user.strip()] = pw.strip()
    return users


def get_user(request: Request) -> str | None:
    """Return the logged-in username from session cookie, or None."""
    token = request.cookies.get("session")
    if token and token in SESSIONS:
        return SESSIONS[token]
    return None


CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { height: 100%; }
body { font-family: georgia, serif; font-size: large; line-height: 1.5; max-width: 40em; margin: 0 auto; overflow-wrap: break-word; padding: 0 1em; padding-top: env(safe-area-inset-top, 1em); padding-bottom: env(safe-area-inset-bottom, 1em); background: #111; color: #bbb; }
a:link { color: #9bf; }
a:visited { color: #a9f; }
a:focus, a:hover { color: #9cf; }
a:active { color: #f99; }
a { text-decoration: none; }
h1, h2, h3, h4, h5, h6 { margin: 1.25em 0 0.25em 0; line-height: 1.2; }
pre, code, samp, kbd { font-family: monospace,monospace; font-size: 0.9em; }
pre code, pre samp, pre kbd { font-size: 1.0em; }
code, pre kbd { color: #9c6; }
samp { color: #db0; }
pre { background: #000; box-shadow: 0 0 0.5em #333; overflow: auto; margin: 1em 0; padding: 0.5em; }
pre code { background: none; }
blockquote { background: #000; box-shadow: 0 0 0.5em #333; border-left: thick solid #333; margin: 1em 0; padding: 0.5em; }
hr { border: 0; border-bottom: 0.15em dotted #666; margin: 1.5em auto; }
.login-form { max-width: 100%; min-height: 80vh; display: flex; flex-direction: column; justify-content: center; }
.login-form input { display: block; width: 100%; padding: 0.5em; margin: 0.5em 0; background: #000; color: #bbb; border: 1px solid #333; font-family: georgia, serif; font-size: 1em; }
.login-form button { width: 100%; padding: 0.5em; cursor: pointer; background: #000; color: #9bf; border: 1px solid #333; font-family: georgia, serif; font-size: 1em; margin-top: 0.5em; }
.login-form button:hover { color: #9cf; }
.logo { width: 4em; height: 4em; border-radius: 50%; border: 0.15em solid #9bf; margin: 0 auto 1.5em; animation: pulse 3s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(153,187,255,0.4); } 50% { box-shadow: 0 0 1.5em 0.3em rgba(153,187,255,0.15); } }
.breadcrumb { margin-bottom: 1em; font-size: 0.85em; overflow-x: auto; white-space: nowrap; }
.file-list { list-style: none; }
.file-list li { padding: 0.4em 0; border-bottom: 1px solid #222; }
.file-list li:last-child { border-bottom: none; }
.meta { color: #666; font-size: 0.85em; }
nav { display: flex; justify-content: space-between; align-items: center; border-bottom: 0.15em dotted #666; margin-bottom: 1em; font-size: 0.9em; }
nav .tabs { display: flex; gap: 0; margin: 0; border: none; }
nav .tab { padding: 0.4em 1em; color: #666; border-bottom: 0.15em solid transparent; margin-bottom: -0.15em; }
nav .tab.active { color: #9bf; border-bottom-color: #9bf; }
nav .account { white-space: nowrap; }
.error { color: #f99; }
.note-list { list-style: none; }
.note-list li { border-bottom: 1px solid #222; }
.note-list li:last-child { border-bottom: none; }
.note-list a { display: block; padding: 0.75em 0; }
.note-title { font-size: 1em; font-weight: bold; color: #bbb; margin-bottom: 0.2em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.note-date { font-size: 0.75em; color: #666; margin-bottom: 0.15em; }
.note-snippet { font-size: 0.85em; color: #888; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.md-content { line-height: 1.5; }
.md-content h1, .md-content h2, .md-content h3, .md-content h4 { margin: 1.25em 0 0.25em; line-height: 1.2; }
.md-content p { margin: 0.75em 0; }
.md-content ul, .md-content ol { margin: 0.75em 0; padding-left: 1.5em; }
.md-content li { margin: 0.25em 0; }
.md-content blockquote { background: #000; box-shadow: 0 0 0.5em #333; border-left: thick solid #333; margin: 1em 0; padding: 0.5em; color: #888; }
.md-content hr { border: 0; border-bottom: 0.15em dotted #666; margin: 1.5em auto; }
.md-content img { max-width: 100%; }
.md-content table { border-collapse: collapse; width: 100%; margin: 0.75em 0; }
.md-content th, .md-content td { border: 1px solid #333; padding: 0.4em 0.6em; text-align: left; }
.md-content th { background: #000; }
"""

# Lightweight markdown to HTML (no external deps)
import re

def _md_to_html(text: str) -> str:
    """Convert markdown to HTML. Handles the common cases."""
    lines = text.split("\n")
    html_parts: list[str] = []
    in_code_block = False
    code_buf: list[str] = []
    in_list = False
    list_type = ""

    def _close_list():
        nonlocal in_list, list_type
        if in_list:
            html_parts.append(f"</{list_type}>")
            in_list = False

    def _inline(line: str) -> str:
        # code spans first (so inner markup isn't processed)
        line = re.sub(r'`([^`]+)`', r'<code>\1</code>', line)
        # images before links
        line = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1">', line)
        # links
        line = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', line)
        # bold + italic
        line = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', line)
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        line = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
        return line

    for line in lines:
        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                html_parts.append("<pre><code>" + html_mod.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
                in_code_block = False
            else:
                _close_list()
                in_code_block = True
            continue
        if in_code_block:
            code_buf.append(line)
            continue

        stripped = line.strip()

        # Empty line
        if not stripped:
            _close_list()
            continue

        # Headings
        m = re.match(r'^(#{1,6})\s+(.*)', stripped)
        if m:
            _close_list()
            level = len(m.group(1))
            html_parts.append(f"<h{level}>{_inline(html_mod.escape(m.group(2)))}</h{level}>")
            continue

        # Horizontal rule
        if re.match(r'^[-*_]{3,}\s*$', stripped):
            _close_list()
            html_parts.append("<hr>")
            continue

        # Blockquote
        if stripped.startswith(">"):
            _close_list()
            content = stripped.lstrip("> ").strip()
            html_parts.append(f"<blockquote><p>{_inline(html_mod.escape(content))}</p></blockquote>")
            continue

        # Unordered list
        m = re.match(r'^[-*+]\s+(.*)', stripped)
        if m:
            if not in_list or list_type != "ul":
                _close_list()
                html_parts.append("<ul>")
                in_list = True
                list_type = "ul"
            html_parts.append(f"<li>{_inline(html_mod.escape(m.group(1)))}</li>")
            continue

        # Ordered list
        m = re.match(r'^\d+\.\s+(.*)', stripped)
        if m:
            if not in_list or list_type != "ol":
                _close_list()
                html_parts.append("<ol>")
                in_list = True
                list_type = "ol"
            html_parts.append(f"<li>{_inline(html_mod.escape(m.group(1)))}</li>")
            continue

        # Paragraph
        _close_list()
        html_parts.append(f"<p>{_inline(html_mod.escape(stripped))}</p>")

    if in_code_block:
        html_parts.append("<pre><code>" + html_mod.escape("\n".join(code_buf)) + "</code></pre>")
    _close_list()

    return "\n".join(html_parts)


def page(title: str, body: str, user: str | None = None, active_tab: str | None = None) -> HTMLResponse:
    nav_html = ""
    if user:
        nc = ' class="tab active"' if active_tab == "notes" else ' class="tab"'
        fc = ' class="tab active"' if active_tab == "files" else ' class="tab"'
        tabs = f'<div class="tabs"><a href="/notes/"{nc}>Notes</a><a href="/browse/"{fc}>Files</a></div>' if active_tab else ''
        nav_html = f'<nav>{tabs}<span class="account">{user} · <a href="/logout">logout</a></span></nav>'
    html = f'<!doctype html><html><head><meta charset=utf-8><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><title>{title}</title><style>{CSS}</style></head><body>{nav_html}{body}</body></html>'
    return HTMLResponse(html)


@app.get("/")
async def root(request: Request):
    if get_user(request):
        return RedirectResponse("/notes/", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/login")
async def login_page(request: Request):
    if get_user(request):
        return RedirectResponse("/notes/", status_code=302)
    body = """
    <div class="login-form">
        <div class="logo"></div>
        <form method="post" action="/login">
            <input name="username" placeholder="username" required autofocus>
            <input name="password" type="password" placeholder="password" required>
            <button type="submit">log in</button>
        </form>
    </div>
    """
    return page("login", body)


@app.post("/login")
async def login_submit(username: str = Form(), password: str = Form()):
    expected = PASSWD.get(username)
    if expected is None or not bcrypt.checkpw(password.encode(), expected.encode()):
        body = """
        <div class="login-form">
            <div class="logo"></div>
            <p class="error">invalid credentials</p>
            <form method="post" action="/login">
                <input name="username" placeholder="username" required autofocus>
                <input name="password" type="password" placeholder="password" required>
                <button type="submit">log in</button>
            </form>
        </div>
        """
        return page("login", body)
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = username
    resp = RedirectResponse("/notes/", status_code=302)
    resp.set_cookie("session", token, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token:
        SESSIONS.pop(token, None)
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session")
    return resp


# ── Notes tab (/www directory, rendered markdown) ──────────────────────

def _note_title(filepath: str, text: str) -> str:
    """Extract a title: first heading, or first non-empty line, or filename."""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^#{1,6}\s+(.*)', line)
        if m:
            return m.group(1)
        return line[:80]
    return filepath.rsplit("/", 1)[-1]


def _note_snippet(text: str) -> str:
    """First non-title, non-empty line as a snippet."""
    found_first = False
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if not found_first:
            found_first = True
            continue
        # skip heading markers
        line = re.sub(r'^#{1,6}\s+', '', line)
        if line:
            return line[:120]
    return ""


@app.get("/notes/")
async def notes_list(request: Request):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    vault = Vault(FSIMAGE, user)
    metas = vault.list_with_metadata(sort_by_recent=True, prefix="www")
    # Filter to only direct files (not directories)
    www_prefix = "www/"

    items_html = ""
    for meta in metas:
        fp = meta.filepath
        if not fp.startswith(www_prefix):
            continue
        rel = fp[len(www_prefix):]
        # Read content for title/snippet
        try:
            content = vault.read(fp).decode("utf-8", errors="replace")
        except FileNotFoundError:
            continue
        title = html_mod.escape(_note_title(rel, content))
        snippet = html_mod.escape(_note_snippet(content))
        date = meta.timestamp or ""
        href = f"/notes/{rel}"
        items_html += (
            f'<li><a href="{href}">'
            f'<div class="note-title">{title}</div>'
            f'<div class="note-date">{date}</div>'
            f'<div class="note-snippet">{snippet}</div>'
            f'</a></li>'
        )

    if not items_html:
        items_html = "<li style='padding:1rem 0;color:#888'><em>No notes yet. Add .md files to /www in the vault.</em></li>"

    body = f"<ul class='note-list'>{items_html}</ul>"
    return page("notes", body, user=user, active_tab="notes")


@app.get("/notes/{path:path}")
async def note_view(request: Request, path: str):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    vault = Vault(FSIMAGE, user)
    vault_path = "www/" + path.strip("/")

    if not vault.exists(vault_path) or vault.is_dir(vault_path):
        return page("not found", "<p>Note not found.</p>", user=user, active_tab="notes")

    try:
        content = vault.read(vault_path).decode("utf-8", errors="replace")
    except FileNotFoundError:
        return page("not found", "<p>Note not found.</p>", user=user, active_tab="notes")

    name = path.rsplit("/", 1)[-1]

    # Render .md files as markdown, others as pre
    if name.endswith(".md"):
        rendered = _md_to_html(content)
        body = f'<div style="margin-bottom:0.5rem"><a href="/notes/">&larr; notes</a></div><div class="md-content">{rendered}</div>'
    else:
        escaped = html_mod.escape(content)
        body = f'<div style="margin-bottom:0.5rem"><a href="/notes/">&larr; notes</a></div><pre>{escaped}</pre>'

    return page(name, body, user=user, active_tab="notes")


# ── Files tab (full filesystem browser) ────────────────────────────────

def _breadcrumb(path: str) -> str:
    """Build an HTML breadcrumb trail for the given vault path."""
    parts = [p for p in path.strip("/").split("/") if p]
    crumbs = ['<a href="/browse/">root</a>']
    for i, part in enumerate(parts):
        href = "/browse/" + "/".join(parts[: i + 1]) + "/"
        crumbs.append(f'<a href="{href}">{part}</a>')
    return '<div class="breadcrumb">' + " / ".join(crumbs) + "</div>"


@app.get("/browse/{path:path}")
async def browse(request: Request, path: str = ""):
    user = get_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    vault = Vault(FSIMAGE, user)
    path = path.strip("/")

    # Check if this is a file
    if path and vault.exists(path) and not vault.is_dir(path):
        try:
            content = vault.read(path)
            text = content.decode("utf-8", errors="replace")
        except FileNotFoundError:
            return page("not found", "<p>File not found.</p>", user=user, active_tab="files")

        name = path.rsplit("/", 1)[-1]
        if name.endswith(".md"):
            rendered = _md_to_html(text)
            body = _breadcrumb(path) + f"<h2>{name}</h2><div class='md-content'>{rendered}</div>"
        else:
            escaped = html_mod.escape(text)
            body = _breadcrumb(path) + f"<h2>{name}</h2><pre>{escaped}</pre>"
        return page(name, body, user=user, active_tab="files")

    # Directory listing
    all_files = vault.list(prefix=path)
    prefix = (path + "/") if path else ""

    # Collect immediate children: files and subdirectories
    dirs: set[str] = set()
    files: set[str] = set()
    for fp in all_files:
        rel = fp[len(prefix):] if prefix else fp
        if "/" in rel:
            dirs.add(rel.split("/")[0])
        else:
            files.add(rel)

    items_html = ""
    for d in sorted(dirs):
        href = f"/browse/{prefix}{d}/"
        items_html += f'<li><a href="{href}">📁 {d}/</a></li>'
    for f in sorted(files):
        href = f"/browse/{prefix}{f}"
        items_html += f'<li><a href="{href}">📄 {f}</a></li>'

    if not items_html:
        items_html = "<li><em>empty directory</em></li>"

    dirname = path or "/"
    body = _breadcrumb(path) + f"<h2>{dirname}</h2><ul class='file-list'>{items_html}</ul>"
    return page(dirname, body, user=user, active_tab="files")


def main():
    parser = argparse.ArgumentParser(description="Vault Web UI")
    parser.add_argument("--fsimage", help="Path to vault SQLite database")
    parser.add_argument("--passwd", help="Path to passwd file (user:bcrypt_hash per line)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--hash-password", metavar="PASSWORD", help="Hash a password and print the bcrypt hash, then exit")
    args = parser.parse_args()

    if args.hash_password:
        hashed = bcrypt.hashpw(args.hash_password.encode(), bcrypt.gensalt()).decode()
        print(hashed)  # no-ctx-print
        sys.exit(0)

    if not args.fsimage or not args.passwd:
        parser.error("--fsimage and --passwd are required when running the server")

    global FSIMAGE, PASSWD
    FSIMAGE = args.fsimage
    PASSWD = load_passwd(args.passwd)

    if not PASSWD:
        print("error: no users found in passwd file", file=sys.stderr)  # no-ctx-print
        sys.exit(1)

    print(f"Loaded {len(PASSWD)} user(s) from {args.passwd}")  # no-ctx-print
    print(f"Vault: {args.fsimage}")  # no-ctx-print

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
