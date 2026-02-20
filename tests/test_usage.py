"""Tests for the usage command."""

from datetime import timedelta

import pytest

from bin.usage import parse_timespan, parse_trajectory, aggregate, compute_cost
from fs.vault import Vault


# ========== parse_timespan ==========


def test_parse_timespan_hours():
    assert parse_timespan("24h") == timedelta(hours=24)
    assert parse_timespan("1h") == timedelta(hours=1)


def test_parse_timespan_days():
    assert parse_timespan("7d") == timedelta(days=7)
    assert parse_timespan("31d") == timedelta(days=31)


def test_parse_timespan_minutes():
    assert parse_timespan("30m") == timedelta(minutes=30)
    assert parse_timespan("5m") == timedelta(minutes=5)


def test_parse_timespan_invalid():
    with pytest.raises(ValueError):
        parse_timespan("abc")

    with pytest.raises(ValueError):
        parse_timespan("10x")

    with pytest.raises(ValueError):
        parse_timespan("")


# ========== compute_cost ==========


def test_compute_cost_known_model():
    # gpt-5-mini: $0.25/1M input, $2.00/1M output
    cost = compute_cost("gpt-5-mini", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.25 + 2.00)


def test_compute_cost_with_provider_prefix():
    # "openai gpt-5-mini" should strip prefix and produce same result
    cost = compute_cost("openai gpt-5-mini", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.25 + 2.00)


def test_compute_cost_gpt5():
    # gpt-5: $1.25/1M input, $10.00/1M output
    cost = compute_cost("gpt-5", 500_000, 200_000)
    assert cost == pytest.approx(0.625 + 2.00)


def test_compute_cost_unknown_model():
    # Unknown models return 0.0
    assert compute_cost("gpt-3", 1_000_000, 1_000_000) == 0.0
    assert compute_cost("", 1_000_000, 1_000_000) == 0.0


# ========== parse_trajectory ==========


SAMPLE_COMPLETED = """\
bin/helper
.MODEL openai gpt-5-mini
.SYSTEM_PROMPT
You are a helpful assistant.
.PROMPT
Working Directory: /

Hello world
.RESPONSE
{"type": "message", "text": "Hi there!"}
.USAGE
{"input_tokens": 150, "output_tokens": 42}
.COMPLETED
"""

SAMPLE_ERROR = """\
bin/helper
.MODEL openai gpt-5
.SYSTEM_PROMPT
You are a helpful assistant.
.PROMPT
Working Directory: /

Do something
.RESPONSE
{"type": "message", "text": "Trying..."}
.ERROR
Connection timed out
"""

SAMPLE_IN_PROGRESS = """\
bin/helper
.MODEL openai gpt-5-mini
.SYSTEM_PROMPT
You are a helpful assistant.
.PROMPT
Working Directory: /

Still running
.RESPONSE
{"type": "tool_call", "name": "read", "arguments": "{}"}
"""


def test_parse_trajectory_completed():
    result = parse_trajectory(SAMPLE_COMPLETED)
    assert result["model"] == "openai gpt-5-mini"
    assert result["input_tokens"] == 150
    assert result["output_tokens"] == 42
    assert result["status"] == "completed"


def test_parse_trajectory_error():
    result = parse_trajectory(SAMPLE_ERROR)
    assert result["model"] == "openai gpt-5"
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0
    assert result["status"] == "error"


def test_parse_trajectory_in_progress():
    result = parse_trajectory(SAMPLE_IN_PROGRESS)
    assert result["model"] == "openai gpt-5-mini"
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0
    assert result["status"] == "in_progress"


# ========== aggregate ==========


def test_aggregate():
    trajectories = [
        {"model": "openai gpt-5-mini", "input_tokens": 100, "output_tokens": 50, "status": "completed"},
        {"model": "openai gpt-5-mini", "input_tokens": 200, "output_tokens": 80, "status": "completed"},
        {"model": "openai gpt-5", "input_tokens": 500, "output_tokens": 200, "status": "error"},
    ]
    result = aggregate(trajectories)

    assert result["sessions"] == 3
    assert result["completed"] == 2
    assert result["errors"] == 1
    assert result["input_tokens"] == 800
    assert result["output_tokens"] == 330
    assert result["models"]["openai gpt-5-mini"] == 2
    assert result["models"]["openai gpt-5"] == 1

    # gpt-5-mini: (300 input * 0.25 + 130 output * 2.00) / 1M
    # gpt-5:      (500 input * 1.25 + 200 output * 10.00) / 1M
    expected_cost = (300 * 0.25 + 130 * 2.00 + 500 * 1.25 + 200 * 10.00) / 1_000_000
    assert result["cost"] == pytest.approx(expected_cost)


def test_aggregate_empty():
    result = aggregate([])
    assert result["sessions"] == 0
    assert result["completed"] == 0
    assert result["errors"] == 0
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0
    assert result["cost"] == 0.0
    assert result["models"] == {}


# ========== integration: collect from vault ==========


def test_collect_usage_from_vault(temp_db):
    """Write trajectory files to a vault, then collect and aggregate them."""
    from bin.usage import collect_usage

    vault = Vault(temp_db, "testuser")

    vault.write("var/trajectories/aaa", SAMPLE_COMPLETED.encode())
    vault.write("var/trajectories/bbb", SAMPLE_ERROR.encode())

    result = collect_usage(vault, timedelta(hours=24))

    assert result["sessions"] == 2
    assert result["completed"] == 1
    assert result["errors"] == 1
    assert result["input_tokens"] == 150
    assert result["output_tokens"] == 42
    assert "openai gpt-5-mini" in result["models"]
    assert "openai gpt-5" in result["models"]
