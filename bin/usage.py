"""Usage statistics from trajectory files."""

import json
import re
from datetime import datetime, timedelta


def parse_timespan(s: str) -> timedelta:
    """Parse a time span string like '24h', '7d', '30m'.

    :param s: Time span string (number + unit: m=minutes, h=hours, d=days)
    :return: A timedelta representing the span
    :raises ValueError: If the string is not a valid time span
    """
    m = re.fullmatch(r"(\d+)([mhd])", s)
    if not m:
        raise ValueError(f"Invalid time span: '{s}'. Use e.g. 30m, 24h, 7d")
    value = int(m.group(1))
    unit = m.group(2)
    if unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    else:
        return timedelta(days=value)


def parse_trajectory(content: str) -> dict:
    """Extract model, token usage, and status from a trajectory file.

    :param content: The raw text content of the trajectory file
    :return: dict with keys: model, input_tokens, output_tokens, status
    """
    model = None
    input_tokens = 0
    output_tokens = 0
    status = "in_progress"

    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(".MODEL "):
            model = line[len(".MODEL "):]
        elif line == ".USAGE" and i + 1 < len(lines):
            try:
                usage = json.loads(lines[i + 1])
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
            except (json.JSONDecodeError, IndexError):
                pass
        elif line == ".COMPLETED":
            status = "completed"
        elif line == ".ERROR":
            status = "error"

    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "status": status,
    }


def aggregate(trajectories: list[dict]) -> dict:
    """Aggregate parsed trajectory data into summary statistics.

    :param trajectories: List of dicts from parse_trajectory()
    :return: dict with sessions, completed, errors, input_tokens, output_tokens, models
    """
    models: dict[str, int] = {}
    total_input = 0
    total_output = 0
    completed = 0
    errors = 0

    for t in trajectories:
        total_input += t["input_tokens"]
        total_output += t["output_tokens"]
        if t["status"] == "completed":
            completed += 1
        elif t["status"] == "error":
            errors += 1
        model = t.get("model")
        if model:
            models[model] = models.get(model, 0) + 1

    return {
        "sessions": len(trajectories),
        "completed": completed,
        "errors": errors,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "models": models,
    }


def collect_usage(vault, span: timedelta) -> dict:
    """Collect and aggregate usage from trajectory files in a vault.

    :param vault: A Vault or OverlayFS instance
    :param span: Time window to look back from now
    :return: Aggregated stats dict from aggregate()
    """
    now = datetime.now()
    cutoff = now - span
    metas = vault.list_with_metadata()

    trajectories = []
    for meta in metas:
        if not meta.filepath.startswith("var/trajectories/"):
            continue
        # Filter by timestamp
        if meta.timestamp:
            try:
                ts = datetime.fromisoformat(meta.timestamp)
                if ts < cutoff:
                    continue
            except ValueError:
                pass  # can't parse timestamp, include it
        # Read and parse
        try:
            content = vault.read(meta.filepath).decode("utf-8", errors="replace")
            trajectories.append(parse_trajectory(content))
        except (FileNotFoundError, UnicodeDecodeError):
            continue

    return aggregate(trajectories)


def collect_active_agents(vault) -> list[dict]:
    """Collect active agent info from /proc entries.

    :param vault: A Vault or OverlayFS instance
    :return: List of dicts with keys: pid, name, trajectory
    """
    agents = []
    try:
        files = vault.list()
    except Exception:
        return agents

    for filepath in files:
        if not filepath.startswith("proc/"):
            continue
        pid = filepath[len("proc/"):]
        # Skip nested paths (only direct children of proc/)
        if "/" in pid:
            continue
        try:
            content = vault.read(filepath).decode("utf-8", errors="replace")
        except (FileNotFoundError, UnicodeDecodeError):
            continue
        # Parse: <agent 'name' trajectory='path'> running
        name = pid  # fallback
        trajectory = None
        if content.startswith("<agent '"):
            rest = content[len("<agent '"):]
            end_name = rest.find("'")
            if end_name != -1:
                name = rest[:end_name]
            traj_marker = "trajectory='"
            traj_idx = rest.find(traj_marker)
            if traj_idx != -1:
                traj_rest = rest[traj_idx + len(traj_marker):]
                end_traj = traj_rest.find("'")
                if end_traj != -1:
                    trajectory = traj_rest[:end_traj]
        agents.append({"pid": pid, "name": name, "trajectory": trajectory})

    return agents


def format_usage(stats: dict, span_label: str, active_agents: list[dict] | None = None) -> str:
    """Format aggregated stats for display.

    :param stats: dict from aggregate()
    :param span_label: Human-readable span like "24h"
    :param active_agents: Optional list of active agent dicts from collect_active_agents()
    :return: Formatted multi-line string
    """
    lines = [f"Usage (last {span_label}):"]

    # Active Agents
    if active_agents:
        lines.append(f"  Active Agents: {len(active_agents)}")
        for agent in active_agents:
            lines.append(f"    - {agent['name']} (pid: {agent['pid'][:8]})")
    else:
        lines.append("  Active Agents: 0")

    # Sessions
    parts = []
    if stats["completed"]:
        parts.append(f"{stats['completed']} completed")
    if stats["errors"]:
        parts.append(f"{stats['errors']} errors")
    in_progress = stats["sessions"] - stats["completed"] - stats["errors"]
    if in_progress:
        parts.append(f"{in_progress} in progress")
    detail = f" ({', '.join(parts)})" if parts else ""
    lines.append(f"  Sessions:  {stats['sessions']}{detail}")

    # Tokens
    inp = f"{stats['input_tokens']:,}"
    out = f"{stats['output_tokens']:,}"
    total = f"{stats['input_tokens'] + stats['output_tokens']:,}"
    lines.append(f"  Tokens:    {inp} input / {out} output ({total} total)")

    # Models
    if stats["models"]:
        model_parts = [f"{m} ({c})" for m, c in sorted(stats["models"].items(), key=lambda x: -x[1])]
        lines.append(f"  Models:    {', '.join(model_parts)}")
    else:
        lines.append("  Models:    (none)")

    return "\n".join(lines)


async def run(*args):
    """Show usage statistics from trajectory files."""
    from system.context import SystemContext

    ctx = SystemContext.current()
    if not ctx:
        print("No context found. Please run this command within a SystemContext.")
        return

    if len(args) > 1:
        print("Usage: usage [TIMESPAN]")
        print("  TIMESPAN: e.g. 30m, 24h, 7d (default: 24h)")
        return

    span_str = args[0] if args else "24h"
    try:
        span = parse_timespan(span_str)
    except ValueError as e:
        print(str(e))
        return

    vault = ctx.fs()
    stats = collect_usage(vault, span)
    active_agents = collect_active_agents(vault)
    print(format_usage(stats, span_str, active_agents))
