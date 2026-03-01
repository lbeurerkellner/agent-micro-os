"""Usage statistics from trajectory files."""

import json
import re
from datetime import datetime, timedelta

# Pricing per 1M tokens (input, output) for supported -5 generation models
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.2":             (1.75,  14.00),
    "gpt-5.1":             (1.25,  10.00),
    "gpt-5":               (1.25,  10.00),
    "gpt-5-mini":          (0.25,   2.00),
    "gpt-5-nano":          (0.05,   0.40),
    "gpt-5.2-chat-latest": (1.75,  14.00),
    "gpt-5.1-chat-latest": (1.25,  10.00),
    "gpt-5-chat-latest":   (1.25,  10.00),
    "gpt-5.2-codex":       (1.75,  14.00),
    "gpt-5.1-codex-max":   (1.25,  10.00),
    "gpt-5.1-codex":       (1.25,  10.00),
    "gpt-5-codex":         (1.25,  10.00),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute the cost in USD for a given model and token usage.

    :param model: Model identifier, optionally prefixed with provider (e.g. "openai gpt-5-mini")
    :param input_tokens: Number of input tokens consumed
    :param output_tokens: Number of output tokens generated
    :return: Cost in USD
    """
    # Strip provider prefix if present (e.g. "openai gpt-5-mini" -> "gpt-5-mini")
    if " " in model:
        model = model.split(" ", 1)[1]
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return 0.0
    input_price, output_price = pricing
    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price


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
    total_cost = 0.0
    completed = 0
    errors = 0

    for t in trajectories:
        total_input += t["input_tokens"]
        total_output += t["output_tokens"]
        total_cost += compute_cost(t.get("model") or "", t["input_tokens"], t["output_tokens"])
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
        "cost": total_cost,
        "models": models,
    }


def collect_usage(vault, span: timedelta) -> dict:
    """Collect and aggregate usage from all agent sessions in a vault.

    :param vault: A Vault or OverlayFS instance
    :param span: Time window to look back from now
    :return: Aggregated stats dict from aggregate()
    """
    from system.sessions import collect_all_sessions

    cutoff = datetime.now() - span
    sessions = collect_all_sessions(vault, cutoff_ts=cutoff)

    trajectories = []
    for s in sessions:
        trajectories.append({
            "model": s.model,
            "input_tokens": s.input_tokens,
            "output_tokens": s.output_tokens,
            "status": s.status,
        })

    return aggregate(trajectories)


def collect_active_agents(vault) -> list[dict]:
    """Collect active agent info from /proc entries.

    :param vault: A Vault or OverlayFS instance
    :return: List of dicts with keys: pid, name, trajectory
    """
    agents = []
    try:
        files = vault.list(prefix="proc")
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


def format_cost_bar(cost: float, limit: float, width: int = 30) -> str:
    """Format a cost-vs-limit progress bar.

    :param cost: Current cost in USD
    :param limit: Cost limit in USD
    :param width: Bar width in characters
    :return: String like "[████░░░░░░░░░░░░░░░░░░░░░░░░░░]  12.3%"
    """
    pct = min(cost / limit, 1.0) if limit > 0 else 0.0
    filled = round(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    real_pct = (cost / limit) if limit > 0 else 0.0
    return f"{bar} {real_pct * 100:5.1f}%"


def format_usage(stats: dict, span_label: str, active_agents: list[dict] | None = None, cost_limit: float | None = None) -> str:
    """Format aggregated stats for display.

    :param stats: dict from aggregate()
    :param span_label: Human-readable span like "24h"
    :param active_agents: Optional list of active agent dicts from collect_active_agents()
    :param cost_limit: Optional cost limit in USD to display a progress bar
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
    if stats["errors"]:
        parts.append(f"{stats['errors']} errors")
    detail = f" ({', '.join(parts)})" if parts else ""
    lines.append(f"  Sessions:  {stats['sessions']}{detail}")

    # Tokens
    inp = f"{stats['input_tokens']:,}"
    out = f"{stats['output_tokens']:,}"
    total = f"{stats['input_tokens'] + stats['output_tokens']:,}"
    lines.append(f"  Tokens:    {inp} input / {out} output ({total} total)")

    # Cost (with optional progress bar when a limit is set)
    cost = stats.get("cost", 0.0)
    if cost_limit is not None:
        bar = format_cost_bar(cost, cost_limit)
        lines.append(f"  Cost:      ${cost:.4f} / ${cost_limit:.2f}  {bar}")
    else:
        lines.append(f"  Cost:      ${cost:.4f}")

    # Models
    if stats["models"]:
        model_parts = [f"{m} ({c})" for m, c in sorted(stats["models"].items(), key=lambda x: -x[1])]
        lines.append(f"  Models:    {', '.join(model_parts)}")
    else:
        lines.append("  Models:    (none)")

    return "\n".join(lines)


async def run(*args):
    """Show usage statistics from trajectory files."""
    from system.context import SystemContext, cprint

    ctx = SystemContext.current()
    if not ctx:
        cprint("No context found. Please run this command within a SystemContext.")
        return

    if len(args) > 1:
        cprint("Usage: usage [TIMESPAN]")
        cprint("  TIMESPAN: e.g. 30m, 24h, 7d (default: 24h)")
        return

    span_str = args[0] if args else "24h"
    try:
        span = parse_timespan(span_str)
    except ValueError as e:
        cprint(str(e))
        return

    vault = ctx.fs()
    stats = collect_usage(vault, span)
    active_agents = collect_active_agents(vault)
    cprint(format_usage(stats, span_str, active_agents, cost_limit=ctx.cost_limit))
