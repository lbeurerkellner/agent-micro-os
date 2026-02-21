"""Tests for VaultJSONSession, SystemContext.child(), and related changes."""

import asyncio
import io
import json
import pytest

from system.context import SystemContext
from system.session import VaultJSONSession


# ---------------------------------------------------------------------------
# SystemContext: interactive flag and child()
# ---------------------------------------------------------------------------


def test_interactive_defaults_to_false(temp_db):
    with SystemContext(user="bob", fsimage=temp_db) as ctx:
        assert ctx.interactive is False


def test_interactive_can_be_set(temp_db):
    with SystemContext(user="bob", fsimage=temp_db, interactive=True) as ctx:
        assert ctx.interactive is True


def test_child_inherits_properties(temp_db):
    with SystemContext(user="bob", fsimage=temp_db, interactive=True) as ctx:
        ctx.cwd = "/some/dir"
        child = ctx.child()
        assert child.user == ctx.user
        assert child.fsimage == ctx.fsimage
        assert child.cwd == "/some/dir"
        assert child.interactive is True
        assert child.path == ctx.path


def test_child_override_interactive(temp_db):
    with SystemContext(user="bob", fsimage=temp_db, interactive=True) as ctx:
        child = ctx.child(interactive=False)
        assert child.interactive is False
        assert ctx.interactive is True  # parent unchanged


def test_child_override_cwd(temp_db):
    with SystemContext(user="bob", fsimage=temp_db) as ctx:
        ctx.cwd = "/original"
        child = ctx.child(cwd="/override")
        assert child.cwd == "/override"
        assert ctx.cwd == "/original"  # parent unchanged


def test_child_inherits_mounts(temp_db):
    from fs.providers import BinProvider
    with SystemContext(user="bob", fsimage=temp_db) as ctx:
        ctx.mount("sbin", BinProvider())
        child = ctx.child()
        # child should have the same mounts
        assert "sbin" in child._mounts


def test_child_is_context_manager(temp_db):
    with SystemContext(user="bob", fsimage=temp_db) as ctx:
        child = ctx.child(interactive=False)
        with child as c:
            assert SystemContext.current() is c
        # after exiting child, original ctx is back on top
        assert SystemContext.current() is ctx


# ---------------------------------------------------------------------------
# VaultJSONSession
# ---------------------------------------------------------------------------


@pytest.fixture
def session_ctx(temp_db):
    ctx = SystemContext(user="bob", fsimage=temp_db)
    ctx.__enter__()
    yield ctx
    ctx.__exit__(None, None, None)


def make_item(text: str) -> dict:
    return {"role": "user", "content": text}


async def test_session_empty_on_start(session_ctx):
    session = VaultJSONSession("abc123", session_ctx)
    items = await session.get_items()
    assert items == []


async def test_session_add_and_get(session_ctx):
    session = VaultJSONSession("sess1", session_ctx)
    items = [make_item("hello"), make_item("world")]
    await session.add_items(items)
    result = await session.get_items()
    assert len(result) == 2
    assert result[0]["content"] == "hello"
    assert result[1]["content"] == "world"


async def test_session_add_multiple_batches(session_ctx):
    session = VaultJSONSession("sess2", session_ctx)
    await session.add_items([make_item("first")])
    await session.add_items([make_item("second")])
    result = await session.get_items()
    assert len(result) == 2
    assert result[0]["content"] == "first"
    assert result[1]["content"] == "second"


async def test_session_pop_item(session_ctx):
    session = VaultJSONSession("sess3", session_ctx)
    await session.add_items([make_item("a"), make_item("b"), make_item("c")])
    popped = await session.pop_item()
    assert popped["content"] == "c"
    remaining = await session.get_items()
    assert len(remaining) == 2
    assert remaining[-1]["content"] == "b"


async def test_session_pop_empty(session_ctx):
    session = VaultJSONSession("sess_empty", session_ctx)
    result = await session.pop_item()
    assert result is None


async def test_session_clear(session_ctx):
    session = VaultJSONSession("sess4", session_ctx)
    await session.add_items([make_item("x"), make_item("y")])
    await session.clear_session()
    result = await session.get_items()
    assert result == []


async def test_session_limit(session_ctx):
    session = VaultJSONSession("sess5", session_ctx)
    for i in range(10):
        await session.add_items([make_item(str(i))])
    result = await session.get_items(limit=3)
    assert len(result) == 3
    # should return the last 3
    assert result[0]["content"] == "7"
    assert result[1]["content"] == "8"
    assert result[2]["content"] == "9"


async def test_session_stored_in_vault(session_ctx):
    """Session data should be stored as a JSONL file in /var/sessions/."""
    session = VaultJSONSession("stored1", session_ctx)
    await session.add_items([make_item("hello")])
    # read the raw file from the vault
    raw = session_ctx.fs().read("/var/sessions/stored1.jsonl").decode("utf-8")
    lines = [l for l in raw.splitlines() if l.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["content"] == "hello"


# ---------------------------------------------------------------------------
# program.parse() — .INTERACTIVE directive
# ---------------------------------------------------------------------------


def test_parse_interactive_flag(temp_db):
    from system.program import parse
    contents = """.INTERACTIVE
.PROMPT
Do something helpful."""

    with SystemContext(user="bob", fsimage=temp_db) as ctx:
        prog = parse(contents)
        assert prog.is_interactive is True


def test_parse_non_interactive_by_default(temp_db):
    from system.program import parse
    contents = """.PROMPT
Do something helpful."""

    with SystemContext(user="bob", fsimage=temp_db) as ctx:
        prog = parse(contents)
        assert prog.is_interactive is False


# ---------------------------------------------------------------------------
# Bin tool wrappers — list[str] args
# ---------------------------------------------------------------------------


async def test_bin_tool_accepts_list_args(temp_db):
    """Registered bin tools should accept a list of string args."""
    from system.tools import TOOLS, _discover_bin_tools

    # Ensure tools are discovered
    _discover_bin_tools()

    with SystemContext(user="bob", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("hello.txt", b"hello world\n")
        ctx.cwd = "/"

        # cat is a bin tool; call it with list args
        cat_tool = TOOLS.get("cat")
        assert cat_tool is not None, "cat tool should be registered"

        result = await cat_tool(args=["hello.txt"])
        assert "hello world" in result


async def test_bin_tool_accepts_empty_list(temp_db):
    """Bin tools should work with empty list args (defaults)."""
    from system.tools import TOOLS, _discover_bin_tools

    _discover_bin_tools()

    with SystemContext(user="bob", fsimage=temp_db) as ctx:
        ctx.cwd = "/"
        ls_tool = TOOLS.get("ls")
        assert ls_tool is not None, "ls tool should be registered"

        # Should not raise even with empty args
        result = await ls_tool(args=[])
        assert isinstance(result, str)
