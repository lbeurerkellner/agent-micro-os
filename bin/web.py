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
html { height: 100%; -webkit-text-size-adjust: 100%; }
body { font-family: -apple-system, system-ui, sans-serif; min-height: 100%; background: #1a1a2e; color: #e0e0e0; padding: 0.75rem; padding-top: env(safe-area-inset-top, 0.75rem); padding-bottom: env(safe-area-inset-bottom, 0.75rem); padding-left: max(0.75rem, env(safe-area-inset-left)); padding-right: max(0.75rem, env(safe-area-inset-right)); font-size: 15px; line-height: 1.5; }
a { color: #7ec8e3; text-decoration: none; -webkit-tap-highlight-color: transparent; }
a:active { opacity: 0.7; }
pre { background: #16213e; padding: 0.75rem; border-radius: 8px; overflow-x: auto; border: 1px solid #333; font-size: 13px; -webkit-overflow-scrolling: touch; word-break: break-word; white-space: pre-wrap; }
code { background: #16213e; padding: 0.15rem 0.35rem; border-radius: 4px; font-size: 13px; }
pre code { background: none; padding: 0; }
h1 { color: #7ec8e3; font-size: 1.3rem; }
h2 { font-size: 1.1rem; margin-bottom: 0.5rem; word-break: break-all; }
.login-form { max-width: 100%; margin: 3rem auto; padding: 0 0.25rem; }
.login-form input { display: block; width: 100%; padding: 0.75rem; margin: 0.5rem 0; background: #16213e; color: #e0e0e0; border: 1px solid #444; border-radius: 8px; font-size: 16px; -webkit-appearance: none; }
.login-form button { width: 100%; padding: 0.75rem; cursor: pointer; background: #0f3460; color: #e0e0e0; border: 1px solid #555; border-radius: 8px; font-size: 16px; margin-top: 0.5rem; }
.login-form button:active { background: #1a4a7a; }
.breadcrumb { margin-bottom: 0.75rem; font-size: 0.85rem; overflow-x: auto; white-space: nowrap; -webkit-overflow-scrolling: touch; padding-bottom: 0.25rem; }
.file-list { list-style: none; }
.file-list li { padding: 0.5rem 0; border-bottom: 1px solid #ffffff0d; }
.file-list li:last-child { border-bottom: none; }
.file-list li a { display: block; padding: 0.15rem 0; }
.meta { color: #888; font-size: 0.8rem; }
nav { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #333; padding-bottom: 0.5rem; margin-bottom: 0.75rem; gap: 0.5rem; font-size: 0.9rem; }
.error { color: #ff6b6b; }

/* Tabs */
.tabs { display: flex; gap: 0; margin-bottom: 0.75rem; border-bottom: 2px solid #333; }
.tab { padding: 0.6rem 1rem; color: #888; font-size: 0.95rem; border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tab.active { color: #7ec8e3; border-bottom-color: #7ec8e3; }

/* Notes list (Apple Notes style) */
.note-list { list-style: none; }
.note-list li { border-bottom: 1px solid #ffffff0d; }
.note-list li:last-child { border-bottom: none; }
.note-list a { display: block; padding: 0.75rem 0.25rem; }
.note-title { font-size: 1rem; font-weight: 600; color: #e0e0e0; margin-bottom: 0.2rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.note-date { font-size: 0.75rem; color: #888; margin-bottom: 0.15rem; }
.note-snippet { font-size: 0.85rem; color: #999; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Rendered markdown */
.md-content { line-height: 1.7; }
.md-content h1, .md-content h2, .md-content h3, .md-content h4 { color: #7ec8e3; margin: 1rem 0 0.5rem; }
.md-content h1 { font-size: 1.4rem; }
.md-content h2 { font-size: 1.2rem; }
.md-content h3 { font-size: 1.05rem; }
.md-content p { margin: 0.5rem 0; }
.md-content ul, .md-content ol { margin: 0.5rem 0; padding-left: 1.5rem; }
.md-content li { margin: 0.25rem 0; }
.md-content blockquote { border-left: 3px solid #7ec8e3; padding-left: 0.75rem; margin: 0.5rem 0; color: #aaa; }
.md-content hr { border: none; border-top: 1px solid #333; margin: 1rem 0; }
.md-content a { color: #7ec8e3; }
.md-content img { max-width: 100%; border-radius: 6px; }
.md-content table { border-collapse: collapse; width: 100%; margin: 0.5rem 0; }
.md-content th, .md-content td { border: 1px solid #333; padding: 0.4rem 0.6rem; text-align: left; }
.md-content th { background: #16213e; }
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


def _tabs_html(active: str) -> str:
    """Render the tab bar. active is 'notes' or 'files'."""
    nc = ' class="tab active"' if active == "notes" else ' class="tab"'
    fc = ' class="tab active"' if active == "files" else ' class="tab"'
    return f'<div class="tabs"><a href="/notes/"{nc}>Notes</a><a href="/browse/"{fc}>Files</a></div>'


def page(title: str, body: str, user: str | None = None, active_tab: str | None = None) -> HTMLResponse:
    nav_html = ""
    if user:
        nav_html = f'<nav><a href="/notes/">vault</a> <span>{user} · <a href="/logout">logout</a></span></nav>'
    tabs = _tabs_html(active_tab) if active_tab else ""
    html = f'<!doctype html><html><head><meta charset=utf-8><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><title>{title}</title><style>{CSS}</style></head><body>{nav_html}{tabs}{body}</body></html>'
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
        <h1>vault login</h1>
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
            <h1>vault login</h1>
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
        print(hashed)
        sys.exit(0)

    if not args.fsimage or not args.passwd:
        parser.error("--fsimage and --passwd are required when running the server")

    global FSIMAGE, PASSWD
    FSIMAGE = args.fsimage
    PASSWD = load_passwd(args.passwd)

    if not PASSWD:
        print("error: no users found in passwd file", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(PASSWD)} user(s) from {args.passwd}")
    print(f"Vault: {args.fsimage}")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
