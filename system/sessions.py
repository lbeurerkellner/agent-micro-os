"""Unified session discovery across different agent runtimes.

Each runtime (built-in agents, Claude Code, etc.) stores session data in its
own format and location.  This module provides a common ``AgentSession``
dataclass and a registry of *collectors* so that ``top``, ``usage``, and other
consumers can iterate over all sessions with a single call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class AgentSession:
    """Normalised view of one agent session, regardless of runtime."""

    session_id: str
    program: str = "-"
    model: str | None = None
    turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    status: str = "completed"  # completed | error | in_progress
    timestamp: str | None = None  # ISO-8601, last activity
    source: str = "builtin"  # e.g. "builtin", "claude"


# ---------------------------------------------------------------------------
# Built-in trajectory parser
# ---------------------------------------------------------------------------

def parse_builtin_trajectory(content: str) -> AgentSession:
    """Parse a ``/var/trajectories/<id>`` file into an AgentSession."""
    program = None
    model = None
    session_id = None
    turns = 0
    tool_calls = 0
    input_tokens = 0
    output_tokens = 0
    status = "in_progress"

    lines = content.splitlines()
    if lines and not lines[0].startswith(".") and not lines[0].startswith("{"):
        program = lines[0]

    for i, line in enumerate(lines):
        if line.startswith(".MODEL "):
            model = line[len(".MODEL "):]
        elif line.startswith(".SESSION "):
            session_id = line[len(".SESSION "):]
        elif line == ".COMPLETED":
            status = "completed"
        elif line == ".ERROR":
            status = "error"
        elif line == ".USAGE" and i + 1 < len(lines):
            try:
                usage = json.loads(lines[i + 1])
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
            except (json.JSONDecodeError, IndexError):
                pass
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
                t = obj.get("type")
                if t == "message":
                    turns += 1
                elif t == "tool_call":
                    tool_calls += 1
            except json.JSONDecodeError:
                pass

    return AgentSession(
        session_id=session_id or "-",
        program=program or "-",
        model=model,
        turns=turns,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        status=status,
        source="builtin",
    )


# ---------------------------------------------------------------------------
# Claude Code JSONL parser
# ---------------------------------------------------------------------------

def parse_claude_session(content: str) -> AgentSession:
    """Parse a Claude Code ``.jsonl`` session file into an AgentSession."""
    session_id = None
    model = None
    turns = 0
    tool_calls = 0
    input_tokens = 0
    output_tokens = 0
    last_timestamp = None

    for line in content.splitlines():
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if session_id is None:
            session_id = obj.get("sessionId")

        ts = obj.get("timestamp")
        if ts:
            last_timestamp = ts

        msg = obj.get("message")
        if not msg:
            continue

        # Extract model from assistant messages
        if model is None and msg.get("role") == "assistant":
            model = msg.get("model")

        # Count turns (user messages that aren't meta/tool-results)
        if msg.get("role") == "user":
            content_val = msg.get("content")
            if isinstance(content_val, str) and not obj.get("isMeta"):
                turns += 1

        # Count tool calls from assistant messages
        if msg.get("role") == "assistant":
            content_val = msg.get("content")
            if isinstance(content_val, list):
                for block in content_val:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_calls += 1

        # Accumulate token usage from assistant messages
        usage = msg.get("usage")
        if usage and msg.get("role") == "assistant":
            input_tokens += usage.get("input_tokens", 0)
            input_tokens += usage.get("cache_read_input_tokens", 0)
            input_tokens += usage.get("cache_creation_input_tokens", 0)
            output_tokens += usage.get("output_tokens", 0)

    return AgentSession(
        session_id=session_id or "-",
        program="claude",
        model=model,
        turns=turns,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        status="completed",
        timestamp=last_timestamp,
        source="claude",
    )


# ---------------------------------------------------------------------------
# Collectors — each returns a list of AgentSession from a vault
# ---------------------------------------------------------------------------

def collect_builtin_sessions(vault, cutoff_ts=None) -> list[AgentSession]:
    """Collect sessions from ``/var/trajectories/``."""
    sessions = []
    try:
        metas = vault.list_with_metadata(prefix="var/trajectories")
    except Exception:
        return sessions

    for meta in metas:
        if cutoff_ts and meta.timestamp:
            try:
                from datetime import datetime
                ts = datetime.fromisoformat(meta.timestamp)
                if ts < cutoff_ts:
                    continue
            except ValueError:
                pass
        try:
            content = vault.read(meta.filepath).decode("utf-8", errors="replace")
        except (FileNotFoundError, UnicodeDecodeError):
            continue

        session = parse_builtin_trajectory(content)
        session.timestamp = meta.timestamp
        sessions.append(session)

    return sessions


def collect_claude_sessions(vault, cutoff_ts=None) -> list[AgentSession]:
    """Collect sessions from ``agent/.claude/projects/**/*.jsonl``."""
    sessions = []
    try:
        metas = vault.list_with_metadata(prefix="agent/.claude/projects")
    except Exception:
        return sessions

    for meta in metas:
        if not meta.filepath.endswith(".jsonl"):
            continue
        if cutoff_ts and meta.timestamp:
            try:
                from datetime import datetime
                ts = datetime.fromisoformat(meta.timestamp)
                if ts < cutoff_ts:
                    continue
            except ValueError:
                pass
        try:
            content = vault.read(meta.filepath).decode("utf-8", errors="replace")
        except (FileNotFoundError, UnicodeDecodeError):
            continue

        session = parse_claude_session(content)
        if session.timestamp is None:
            session.timestamp = meta.timestamp
        # Skip trivial sessions (no model = no real assistant response)
        if session.model is None:
            continue
        sessions.append(session)

    return sessions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_COLLECTORS = [collect_builtin_sessions, collect_claude_sessions]


def collect_all_sessions(vault, cutoff_ts=None) -> list[AgentSession]:
    """Collect sessions from all registered runtimes.

    :param vault: A Vault or OverlayFS instance
    :param cutoff_ts: Optional datetime cutoff — sessions older than this are skipped
    :return: List of AgentSession, sorted most-recent first
    """
    all_sessions: list[AgentSession] = []
    for collector in _COLLECTORS:
        all_sessions.extend(collector(vault, cutoff_ts=cutoff_ts))

    all_sessions.sort(key=lambda s: s.timestamp or "", reverse=True)
    return all_sessions
