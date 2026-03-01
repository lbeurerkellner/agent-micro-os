"""Tests for the unified session abstraction."""

import json

from system.sessions import (
    AgentSession,
    parse_builtin_trajectory,
    parse_claude_session,
    collect_all_sessions,
    collect_builtin_sessions,
    collect_claude_sessions,
)
from fs.vault import Vault


# ---------------------------------------------------------------------------
# Built-in trajectory parsing
# ---------------------------------------------------------------------------

class TestParseBuiltinTrajectory:

    def test_basic_trajectory(self):
        content = """\
/bin/my-agent
.MODEL openai gpt-5-mini
.SESSION abc123
.PROMPT
Do something
.RESPONSE
{"type": "message", "text": "hello"}
{"type": "tool_call", "name": "ash", "arguments": "ls"}
{"type": "tool_output", "call_id": "x", "output": "file.txt"}
{"type": "message", "text": "done"}
.USAGE
{"input_tokens": 100, "output_tokens": 50}
.COMPLETED"""

        s = parse_builtin_trajectory(content)
        assert s.program == "/bin/my-agent"
        assert s.model == "openai gpt-5-mini"
        assert s.session_id == "abc123"
        assert s.turns == 2
        assert s.tool_calls == 1
        assert s.input_tokens == 100
        assert s.output_tokens == 50
        assert s.status == "completed"
        assert s.source == "builtin"

    def test_error_status(self):
        content = """\
/bin/agent
.MODEL openai gpt-5-mini
.SESSION x
.ERROR"""
        s = parse_builtin_trajectory(content)
        assert s.status == "error"

    def test_in_progress(self):
        content = """\
/bin/agent
.MODEL openai gpt-5-mini
.SESSION x
.RESPONSE
{"type": "message", "text": "thinking..."}"""
        s = parse_builtin_trajectory(content)
        assert s.status == "in_progress"
        assert s.turns == 1


# ---------------------------------------------------------------------------
# Claude Code JSONL parsing
# ---------------------------------------------------------------------------

class TestParseClaudeSession:

    def test_basic_session(self):
        lines = [
            json.dumps({
                "sessionId": "sess-1", "type": "user", "timestamp": "2026-03-01T10:00:00Z",
                "message": {"role": "user", "content": "hi"},
            }),
            json.dumps({
                "sessionId": "sess-1", "type": "assistant", "timestamp": "2026-03-01T10:00:01Z",
                "message": {
                    "role": "assistant", "model": "claude-sonnet-4-6",
                    "content": [{"type": "text", "text": "Hello!"}],
                    "usage": {"input_tokens": 100, "output_tokens": 20,
                              "cache_read_input_tokens": 500,
                              "cache_creation_input_tokens": 0},
                },
            }),
        ]
        content = "\n".join(lines)
        s = parse_claude_session(content)

        assert s.session_id == "sess-1"
        assert s.program == "claude"
        assert s.model == "claude-sonnet-4-6"
        assert s.turns == 1  # one user message
        assert s.tool_calls == 0
        assert s.input_tokens == 600  # 100 + 500
        assert s.output_tokens == 20
        assert s.source == "claude"
        assert s.timestamp == "2026-03-01T10:00:01Z"

    def test_tool_use_counting(self):
        lines = [
            json.dumps({
                "sessionId": "sess-2", "type": "user", "timestamp": "2026-03-01T10:00:00Z",
                "message": {"role": "user", "content": "do something"},
            }),
            json.dumps({
                "sessionId": "sess-2", "type": "assistant", "timestamp": "2026-03-01T10:00:01Z",
                "message": {
                    "role": "assistant", "model": "claude-sonnet-4-6",
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
                        {"type": "tool_use", "id": "t2", "name": "Write", "input": {}},
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5,
                              "cache_read_input_tokens": 0,
                              "cache_creation_input_tokens": 0},
                },
            }),
        ]
        content = "\n".join(lines)
        s = parse_claude_session(content)

        assert s.tool_calls == 2
        assert s.turns == 1

    def test_meta_messages_not_counted_as_turns(self):
        lines = [
            json.dumps({
                "sessionId": "sess-3", "type": "user", "isMeta": True,
                "timestamp": "2026-03-01T10:00:00Z",
                "message": {"role": "user", "content": "<local-command-caveat>...</local-command-caveat>"},
            }),
        ]
        content = "\n".join(lines)
        s = parse_claude_session(content)
        assert s.turns == 0

    def test_skips_non_json_lines(self):
        content = "not json\n{bad json\n"
        s = parse_claude_session(content)
        assert s.session_id == "-"
        assert s.turns == 0

    def test_file_history_snapshots_ignored(self):
        """file-history-snapshot lines should not affect counts."""
        lines = [
            json.dumps({"type": "file-history-snapshot", "messageId": "x", "snapshot": {}}),
            json.dumps({
                "sessionId": "sess-4", "type": "user", "timestamp": "2026-03-01T10:00:00Z",
                "message": {"role": "user", "content": "hello"},
            }),
        ]
        content = "\n".join(lines)
        s = parse_claude_session(content)
        assert s.session_id == "sess-4"
        assert s.turns == 1


# ---------------------------------------------------------------------------
# collect_all_sessions
# ---------------------------------------------------------------------------

class TestCollectAllSessions:

    def test_collects_both_sources(self, temp_db):
        vault = Vault(temp_db, "tester")

        # Built-in trajectory
        vault.write("var/trajectories/traj-1", b"""\
/bin/agent
.MODEL openai gpt-5-mini
.SESSION s1
.COMPLETED""")

        # Claude session (needs both user + assistant message to not be filtered)
        claude_lines = "\n".join([
            json.dumps({
                "sessionId": "claude-s1", "type": "user",
                "timestamp": "2026-03-01T10:00:00Z",
                "message": {"role": "user", "content": "hi"},
            }),
            json.dumps({
                "sessionId": "claude-s1", "type": "assistant",
                "timestamp": "2026-03-01T10:00:01Z",
                "message": {"role": "assistant", "model": "claude-sonnet-4-6",
                            "content": [{"type": "text", "text": "Hello!"}],
                            "usage": {"input_tokens": 10, "output_tokens": 5,
                                      "cache_read_input_tokens": 0,
                                      "cache_creation_input_tokens": 0}},
            }),
        ])
        vault.write(
            "agent/.claude/projects/-workspace/sess-uuid.jsonl",
            claude_lines.encode(),
        )

        sessions = collect_all_sessions(vault)
        sources = {s.source for s in sessions}
        assert "builtin" in sources
        assert "claude" in sources
        assert len(sessions) == 2

    def test_cutoff_filters_old_sessions(self, temp_db):
        from datetime import datetime, timedelta

        vault = Vault(temp_db, "tester")
        vault.write("var/trajectories/traj-1", b"""\
/bin/agent
.MODEL openai gpt-5-mini
.SESSION s1
.COMPLETED""")

        # With a future cutoff, nothing should be returned (trajectory timestamp
        # is "now" at write time, so a cutoff far in the future should exclude it)
        far_future = datetime.now() + timedelta(days=365)
        sessions = collect_all_sessions(vault, cutoff_ts=far_future)
        assert len(sessions) == 0
