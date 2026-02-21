"""Live view of active agent processes."""

import json
import re

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
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

    Returns dict with: program, model, session_id, turns, tool_calls, input_tokens, output_tokens
    """
    stats = {
        "program": None,
        "model": None,
        "session_id": None,
        "turns": 0,
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    lines = content.splitlines()
    # First non-empty line that doesn't start with '.' or '{' is the program path
    if lines and not lines[0].startswith(".") and not lines[0].startswith("{"):
        stats["program"] = lines[0]
    for line in lines:
        if line.startswith(".MODEL "):
            stats["model"] = line[len(".MODEL "):]
            continue
        if line.startswith(".SESSION "):
            stats["session_id"] = line[len(".SESSION "):]
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


def _format_age(timestamp: str | None) -> str:
    """Convert an ISO timestamp to a human-readable relative age string."""
    if not timestamp:
        return "-"
    try:
        from datetime import datetime
        ts = datetime.fromisoformat(timestamp)
        secs = int((datetime.now() - ts).total_seconds())
        if secs < 10:
            return "Just now"
        elif secs < 60:
            return f"{secs}s ago"
        elif secs < 3600:
            return f"{secs // 60}m ago"
        elif secs < 86400:
            return f"{secs // 3600}h ago"
        else:
            return ts.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return "-"


def collect_processes(vault) -> list[dict]:
    """Collect active agent process info from /proc and their trajectories."""
    processes = []
    try:
        files = vault.list(prefix="proc")
    except Exception:
        return processes

    # Build timestamp lookup for trajectory files
    traj_timestamps: dict[str, str | None] = {}
    try:
        for meta in vault.list_with_metadata(prefix="var/trajectories"):
            traj_timestamps[meta.filepath] = meta.timestamp
    except Exception:
        pass

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

        traj = info.get("trajectory")
        if traj:
            try:
                traj_content = vault.read(traj).decode("utf-8", errors="replace")
                stats = parse_trajectory_live(traj_content)
            except (FileNotFoundError, UnicodeDecodeError):
                pass

        # Strip leading slash for metadata lookup
        traj_key = traj.lstrip("/") if traj else None
        processes.append({
            "pid": pid,
            "program": info["program"],
            "session_id": stats.get("session_id") or "-",
            "model": stats["model"] or "-",
            "turns": stats["turns"],
            "tool_calls": stats["tool_calls"],
            "input_tokens": stats["input_tokens"],
            "output_tokens": stats["output_tokens"],
            "last_active": traj_timestamps.get(traj_key),
        })

    return processes


def collect_idle_agents(vault, active_pids: set, active_sessions: set | None = None) -> list[dict]:
    """Collect recently completed agent trajectories not currently running."""
    from datetime import datetime, timedelta

    idle = []
    cutoff = datetime.now() - timedelta(hours=24)

    try:
        metas = vault.list_with_metadata()
    except Exception:
        return idle

    traj_metas = []
    for meta in metas:
        if not meta.filepath.startswith("var/trajectories/"):
            continue
        call_id = meta.filepath[len("var/trajectories/"):]
        if call_id in active_pids:
            continue
        if meta.timestamp:
            try:
                ts = datetime.fromisoformat(meta.timestamp)
                if ts < cutoff:
                    continue
            except ValueError:
                pass
        traj_metas.append(meta)

    # Most recent first
    traj_metas.sort(key=lambda m: m.timestamp or "", reverse=True)

    seen_sessions: set[str] = set(active_sessions or [])
    for meta in traj_metas:
        call_id = meta.filepath[len("var/trajectories/"):]
        try:
            content = vault.read(meta.filepath).decode("utf-8", errors="replace")
        except (FileNotFoundError, UnicodeDecodeError):
            continue
        stats = parse_trajectory_live(content)
        session_id = stats.get("session_id") or "-"
        if session_id != "-" and session_id in seen_sessions:
            continue
        seen_sessions.add(session_id)
        idle.append({
            "pid": call_id,
            "program": stats.get("program") or "-",
            "session_id": session_id,
            "model": stats.get("model") or "-",
            "turns": stats.get("turns", 0),
            "tool_calls": stats.get("tool_calls", 0),
            "input_tokens": stats.get("input_tokens", 0),
            "output_tokens": stats.get("output_tokens", 0),
            "last_active": meta.timestamp,
        })

    return idle


def format_usage_header(stats: dict, cost_limit: float | None = None) -> list[tuple[str, str]]:
    """Format system-wide usage stats as formatted text tuples with bold labels."""
    from bin.usage import format_cost_bar

    total_in = stats["input_tokens"]
    total_out = stats["output_tokens"]
    total = total_in + total_out

    sessions = stats["sessions"]

    parts = []
    if stats["errors"]:
        parts.append(f"{stats['errors']} errors")

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

    # Cost row with optional progress bar
    cost = stats.get("cost", 0.0)
    if cost_limit is not None:
        pct = min(cost / cost_limit, 1.0) if cost_limit > 0 else 0.0
        bar = format_cost_bar(cost, cost_limit)
        if pct >= 1.0:
            bar_style = "fg:ansired bold"
        elif pct >= 0.8:
            bar_style = "fg:ansiyellow"
        else:
            bar_style = "fg:ansigreen"
        ft.append(("bold", "Cost: "))
        ft.append(("", f"${cost:.4f} / ${cost_limit:.2f}  "))
        ft.append((bar_style, bar + "\n"))
    else:
        ft.append(("bold", "Cost: "))
        ft.append(("", f"${cost:.4f}\n"))

    return ft


_COLS = [
    ("STATUS", "status", 8, "left"),
    # ("PID", "pid", 10, "left"),
    ("SESSION", "session_id", 10, "left"),
    ("PROGRAM", "program", 15, "left"),
    ("MODEL", "model", 20, "left"),
    ("TURNS", "turns", 7, "right"),
    ("TOOLS", "tool_calls", 7, "right"),
    ("IN TOK", "input_tokens", 10, "right"),
    ("OUT TOK", "output_tokens", 10, "right"),
    ("LAST ACTIVE", "last_active", 16, "right"),
]


def _build_header() -> str:
    parts = []
    for name, _, width, align in _COLS:
        parts.append(name.rjust(width) if align == "right" else name.ljust(width))
    return "  ".join(parts)


def _format_row(proc: dict) -> str:
    parts = []
    for _, key, width, align in _COLS:
        val = proc.get(key, "-")
        if key == "pid":
            val = str(val)[:8]
        elif key == "session_id":
            val = str(val)[:10]
        elif key in ("input_tokens", "output_tokens"):
            val = f"{val:,}"
        elif key == "last_active":
            val = _format_age(val if val != "-" else None)
        else:
            val = str(val)
        parts.append(val.rjust(width) if align == "right" else val.ljust(width))
    return "  ".join(parts)


def format_combined_table(running: list[dict], idle: list[dict], cursor: int) -> tuple[list[tuple[str, str]], int, int]:
    """Format running and idle agents in one table with cursor highlighting.

    Returns (formatted_text, total_agents, cursor_line_within_table).
    """
    ft: list[tuple[str, str]] = []

    for proc in running:
        proc["status"] = "RUNNING"
    for proc in idle:
        proc["status"] = "IDLE"

    header = _build_header()
    sep = " " * len(header)

    ft.append(("bold", header + "\n"))
    line = 1

    n_run = len(running)
    total = n_run + len(idle)
    cursor_line = 0

    if running:
        ft.append(("", sep + "\n"))
        line += 1
        for i, proc in enumerate(running):
            style = "reverse" if i == cursor else ""
            ft.append((style, _format_row(proc) + "\n"))
            if i == cursor:
                cursor_line = line
            line += 1

    ft.append(("", sep + "\n"))
    line += 1

    if idle:
        for i, proc in enumerate(idle):
            abs_i = n_run + i
            style = "reverse" if abs_i == cursor else ""
            ft.append((style, _format_row(proc) + "\n"))
            if abs_i == cursor:
                cursor_line = line
            line += 1
    else:
        ft.append(("", "  No recent idle agents.\n"))

    return ft, total, cursor_line


async def run(*args):
    """Show live view of active agent processes."""
    import asyncio
    from system.context import SystemContext, cprint

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    vault = ctx.fs()

    # State for the display
    state = {
        "text": [("", "Loading...")],
        "cursor": 0,
        "total": 0,
        "cursor_line": 0,
        "agents": [],
        "procs": [],
        "idle": [],
        "usage_stats": None,
        "mode": "normal",   # "normal" | "input"
        "pending": None,    # {program, session_id, text} set before exit
    }

    def fetch_data():
        """Read all vault state into the cache. Called only from the background refresh loop."""
        from datetime import timedelta
        from bin.usage import collect_usage

        procs = collect_processes(vault)
        active_pids = {p["pid"] for p in procs}
        active_sessions = {p["session_id"] for p in procs if p["session_id"] != "-"}
        idle = collect_idle_agents(vault, active_pids, active_sessions)
        stats = collect_usage(vault, timedelta(hours=24))

        state["procs"] = procs
        state["idle"] = idle
        state["usage_stats"] = stats

        # Clamp cursor now that total may have changed
        total = len(procs) + len(idle)
        state["total"] = total
        state["agents"] = list(procs) + list(idle)
        if total > 0:
            state["cursor"] = max(0, min(state["cursor"], total - 1))
        else:
            state["cursor"] = 0

    def render_display():
        """Re-format cached data into formatted text. No vault I/O."""
        procs = state["procs"]
        idle = state["idle"]
        stats = state["usage_stats"]

        if stats is None:
            state["text"] = [("", "Loading...")]
            return

        cursor = state["cursor"]
        usage_ft = format_usage_header(stats, cost_limit=ctx.cost_limit)
        table_ft, total, table_cursor_line = format_combined_table(procs, idle, cursor)

        # +1 for blank separator line between usage header and table
        usage_lines = sum(text.count("\n") for _, text in usage_ft) + 1
        state["cursor_line"] = usage_lines + table_cursor_line

        ft: list[tuple[str, str]] = []
        ft.extend(usage_ft)
        ft.append(("", "\n"))
        ft.extend(table_ft)
        state["text"] = ft

    # Reactive text control
    def get_text():
        return state["text"]

    def get_help_text():
        if state["mode"] == "input":
            return "top | Follow up with agent | Enter: run agent with prompt | Esc: cancel"
        return "top | q: quit | ↑↓ / j k: move | PgUp PgDn: page | g: top | Enter: open | (refreshes every 1s)"

    def get_input_prompt():
        agents = state["agents"]
        cursor = state["cursor"]
        if agents and cursor < len(agents):
            agent = agents[cursor]
            program = agent.get("program", "?")
            session = agent.get("session_id", "-")
            return [("bold", f"{program}"), ("", f" --session {session}  > ")]
        return [("", "  > ")]

    input_buffer = Buffer(name="input")
    in_input_mode = Condition(lambda: state["mode"] == "input")

    body = FormattedTextControl(text=get_text)
    help_bar = FormattedTextControl(text=get_help_text)
    input_prompt = FormattedTextControl(text=get_input_prompt)
    input_control = BufferControl(buffer=input_buffer)

    body_window = Window(content=body)
    input_window = Window(content=input_control, height=1)

    root = HSplit([
        Window(content=help_bar, height=1),
        Window(content=FormattedTextControl(text=""), height=1),  # spacer
        body_window,
        ConditionalContainer(
            content=VSplit([
                Window(content=input_prompt, dont_extend_width=True),
                input_window,
            ], height=1),
            filter=in_input_mode,
        ),
    ])

    # Key bindings
    kb = KeyBindings()

    @kb.add("q", filter=~in_input_mode)
    def quit_top(event):
        event.app.exit()

    @kb.add("c-c")
    def ctrl_c(event):
        event.app.exit()

    def _ensure_cursor_visible():
        line = state["cursor_line"]
        try:
            height = app.output.get_size().rows - 3  # minus help bar and spacer
        except Exception:
            height = 20
        scroll = body_window.vertical_scroll
        if line < scroll:
            body_window.vertical_scroll = line
        elif line >= scroll + height - 1:
            body_window.vertical_scroll = max(0, line - height + 2)

    def _move_cursor(delta):
        total = state["total"]
        if total == 0:
            return
        state["cursor"] = max(0, min(state["cursor"] + delta, total - 1))
        render_display()
        _ensure_cursor_visible()
        app.invalidate()

    @kb.add("up", filter=~in_input_mode)
    @kb.add("k", filter=~in_input_mode)
    def cursor_up(event):
        _move_cursor(-1)

    @kb.add("down", filter=~in_input_mode)
    @kb.add("j", filter=~in_input_mode)
    def cursor_down(event):
        _move_cursor(1)

    @kb.add("pageup", filter=~in_input_mode)
    def page_up(event):
        _move_cursor(-10)

    @kb.add("pagedown", filter=~in_input_mode)
    def page_down(event):
        _move_cursor(10)

    @kb.add("home", filter=~in_input_mode)
    @kb.add("g", filter=~in_input_mode)
    def goto_top(event):
        state["cursor"] = 0
        render_display()
        body_window.vertical_scroll = 0
        app.invalidate()

    @kb.add("enter", filter=~in_input_mode)
    def open_input(event):
        if state["total"] == 0:
            return
        state["mode"] = "input"
        input_buffer.reset()
        app.layout.focus(input_window)
        app.invalidate()

    @kb.add("escape", filter=in_input_mode)
    def cancel_input(event):
        state["mode"] = "normal"
        input_buffer.reset()
        app.layout.focus(body_window)
        app.invalidate()

    @kb.add("enter", filter=in_input_mode)
    def submit_input(event):
        agents = state["agents"]
        cursor = state["cursor"]
        if not agents or cursor >= len(agents):
            return
        agent = agents[cursor]
        state["pending"] = {
            "program": agent.get("program", ""),
            "session_id": agent.get("session_id", ""),
            "text": input_buffer.text,
        }
        event.app.exit()

    app = Application(
        layout=Layout(root),
        key_bindings=kb,
        full_screen=True,
    )

    # Background refresh task
    async def refresh_loop():
        try:
            while True:
                fetch_data()
                render_display()
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

    # If the user submitted a command via the input pane, run it now
    if state["pending"]:
        from system.execute import execute
        pending = state["pending"]
        program = pending["program"]
        session_id = pending["session_id"]
        text = pending["text"].strip()
        extra_args = text.split() if text else []
        cmd_args = ["--session", session_id] + extra_args
        await execute(ctx, program, *cmd_args)
