"""Live view of active agent processes."""

import json
import re

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout


def parse_proc_entry(content: str) -> dict:
    """Parse a /proc entry into structured data.

    Format: <agent 'program' trajectory='path'> running
    """
    info = {"program": "?", "trajectory": None}
    if content.startswith("<agent '"):
        rest = content[len("<agent '"):]
        end = rest.find("'")
        if end != -1:
            info["program"] = rest[:end]
        m = re.search(r"trajectory='([^']*)'", rest)
        if m:
            info["trajectory"] = m.group(1)
    return info


def parse_trajectory_live(content: str) -> dict:
    """Parse a trajectory file for live stats.

    Returns dict with: model, turns, tool_calls, input_tokens, output_tokens
    """
    stats = {
        "model": None,
        "turns": 0,
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    for line in content.splitlines():
        if line.startswith(".MODEL "):
            stats["model"] = line[len(".MODEL "):]
            continue
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type")
        if t == "message":
            stats["turns"] += 1
        elif t == "tool_call":
            stats["tool_calls"] += 1
        elif t == "usage":
            stats["input_tokens"] = obj.get("input_tokens", 0)
            stats["output_tokens"] = obj.get("output_tokens", 0)
    return stats


def collect_processes(vault) -> list[dict]:
    """Collect active agent process info from /proc and their trajectories."""
    processes = []
    try:
        files = vault.list(prefix="proc")
    except Exception:
        return processes

    for filepath in files:
        if not filepath.startswith("proc/"):
            continue
        pid = filepath[len("proc/"):]
        if "/" in pid:
            continue
        try:
            proc_content = vault.read(filepath).decode("utf-8", errors="replace")
        except (FileNotFoundError, UnicodeDecodeError):
            continue

        info = parse_proc_entry(proc_content)
        stats = {
            "model": None, "turns": 0,
            "tool_calls": 0, "input_tokens": 0, "output_tokens": 0,
        }

        # Read trajectory for live stats
        traj = info.get("trajectory")
        if traj:
            try:
                traj_content = vault.read(traj).decode("utf-8", errors="replace")
                stats = parse_trajectory_live(traj_content)
            except (FileNotFoundError, UnicodeDecodeError):
                pass

        processes.append({
            "pid": pid,
            "program": info["program"],
            "model": stats["model"] or "-",
            "turns": stats["turns"],
            "tool_calls": stats["tool_calls"],
            "input_tokens": stats["input_tokens"],
            "output_tokens": stats["output_tokens"],
        })

    return processes


def format_usage_header(stats: dict) -> list[tuple[str, str]]:
    """Format system-wide usage stats as formatted text tuples with bold labels."""
    total_in = stats["input_tokens"]
    total_out = stats["output_tokens"]
    total = total_in + total_out

    sessions = stats["sessions"]

    parts = []
    if stats["completed"]:
        parts.append(f"{stats['completed']} completed")
    if stats["errors"]:
        parts.append(f"{stats['errors']} errors")
    in_progress = sessions - stats["completed"] - stats["errors"]
    if in_progress:
        parts.append(f"{in_progress} in progress")

    detail = f" ({', '.join(parts)})" if parts else ""

    ft: list[tuple[str, str]] = []
    ft.append(("bold", "Usage: "))
    ft.append(("", f"{total:,} tokens ({total_in:,} in / {total_out:,} out) "))
    ft.append(("bold", "Sessions: "))
    ft.append(("", f"{sessions}{detail}\n"))

    if stats["models"]:
        sorted_models = sorted(stats["models"].items(), key=lambda x: -x[1])
        max_name = max(len(m) for m, _ in sorted_models)
        for model, count in sorted_models:
            padded = model.ljust(max_name)
            ft.append(("", f"  {padded} | {count} session{'s' if count != 1 else ''}\n"))

    return ft


def format_table(processes: list[dict]) -> list[tuple[str, str]]:
    """Format processes into formatted text tuples."""
    if not processes:
        return [("", "No active agents.")]

    # Column definitions: (header, key, width, align)
    cols = [
        ("PID", "pid", 10, "left"),
        ("PROGRAM", "program", 30, "left"),
        ("MODEL", "model", 22, "left"),
        ("TURNS", "turns", 7, "right"),
        ("TOOLS", "tool_calls", 7, "right"),
        ("IN TOK", "input_tokens", 10, "right"),
        ("OUT TOK", "output_tokens", 10, "right"),
    ]

    # Build header
    header_parts = []
    for name, _, width, align in cols:
        if align == "right":
            header_parts.append(name.rjust(width))
        else:
            header_parts.append(name.ljust(width))
    header = "  ".join(header_parts)

    # Build rows
    rows = []
    for proc in processes:
        parts = []
        for _, key, width, align in cols:
            val = proc[key]
            if key == "pid":
                val = str(val)[:8]
            elif key in ("input_tokens", "output_tokens"):
                val = f"{val:,}"
            else:
                val = str(val)
            if align == "right":
                parts.append(val.rjust(width))
            else:
                parts.append(val.ljust(width))
        rows.append("  ".join(parts))

    sep = "-" * len(header)
    ft: list[tuple[str, str]] = []
    ft.append(("bold", header + "\n"))
    ft.append(("", sep + "\n"))
    for row in rows:
        ft.append(("", row + "\n"))
    return ft


async def run(*args):
    """Show live view of active agent processes."""
    import asyncio
    from system.context import SystemContext

    ctx = SystemContext.current()
    if not ctx:
        print("No context found. Please run this command within a SystemContext.")
        return

    vault = ctx.fs()

    # State for the display
    state = {"text": [("", "Loading...")]}

    def get_display_text():
        from datetime import timedelta
        from bin.usage import collect_usage

        procs = collect_processes(vault)
        stats = collect_usage(vault, timedelta(hours=24))

        ft: list[tuple[str, str]] = []
        ft.extend(format_usage_header(stats))
        ft.append(("", "\n"))
        ft.extend(format_table(procs))
        return ft

    # Key bindings
    kb = KeyBindings()

    @kb.add("q")
    def quit_top(event):
        event.app.exit()

    @kb.add("c-c")
    def ctrl_c(event):
        event.app.exit()

    # Reactive text control
    def get_text():
        return state["text"]

    body = FormattedTextControl(text=get_text)
    help_bar = FormattedTextControl(text="  top - live agent monitor    q: quit    (refreshes every 1s)")

    root = HSplit([
        Window(content=help_bar, height=1),
        Window(content=FormattedTextControl(text=""), height=1),  # spacer
        Window(content=body, dont_extend_height=True),
        Window(),  # spacer absorbs remaining space
    ])

    app = Application(
        layout=Layout(root),
        key_bindings=kb,
        full_screen=True,
    )

    # Background refresh task
    async def refresh_loop():
        try:
            while True:
                state["text"] = get_display_text()
                app.invalidate()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def run_app():
        refresh_task = asyncio.create_task(refresh_loop())
        try:
            await app.run_async()
        finally:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass

    await run_app()
