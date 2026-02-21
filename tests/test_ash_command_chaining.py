"""Test ash -c command chaining functionality."""

import io

from system.context import SystemContext
from fs.providers import BinProvider
from bin.ash import run_command


async def test_cd_and_cat_chain(temp_db):
    """Test that cd && cat works correctly."""
    with SystemContext(user="test_user", fsimage=temp_db) as ctx:
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"This is the BRAIN.md file in agent directory\n")
        vault.write("README.md", b"This is the root README\n")

        assert vault.exists("agent/BRAIN.md")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await run_command("cd agent && cat BRAIN.md")

        result = output.getvalue()
        assert "No such file" not in result, f"Got 'No such file' error: {result}"
        assert "BRAIN.md" in result or "agent directory" in result, f"Expected file content, got: {result}"


async def test_redirect_overwrite(temp_db):
    """Test > redirect writes command output to a file."""
    with SystemContext(user="test_user", fsimage=temp_db) as ctx:
        ctx.mount("sbin", BinProvider())

        output = io.StringIO()
        with ctx.child(stdout=output):
            await run_command("echo hello world > /out.txt")

        # Output should NOT appear on stdout (it was redirected)
        assert output.getvalue() == ""

        # File should contain the command output
        content = ctx.fs().read("/out.txt").decode("utf-8")
        assert content.strip() == "hello world"


async def test_redirect_append(temp_db):
    """Test >> redirect appends to an existing file."""
    with SystemContext(user="test_user", fsimage=temp_db) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.fs().write("out.txt", b"line1\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await run_command("echo line2 >> /out.txt")

        content = ctx.fs().read("/out.txt").decode("utf-8")
        assert "line1" in content
        assert "line2" in content


async def test_redirect_with_chain(temp_db):
    """Test && combined with > redirect."""
    with SystemContext(user="test_user", fsimage=temp_db) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.fs().write("hello.txt", b"hello from file\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await run_command("echo first > /a.txt && echo second > /b.txt")

        a = ctx.fs().read("/a.txt").decode("utf-8")
        b = ctx.fs().read("/b.txt").decode("utf-8")
        assert a.strip() == "first"
        assert b.strip() == "second"


async def test_quoted_ampersand_not_split(temp_db):
    """Test that && inside quotes is not treated as a chain operator."""
    with SystemContext(user="test_user", fsimage=temp_db) as ctx:
        ctx.mount("sbin", BinProvider())

        output = io.StringIO()
        with ctx.child(stdout=output):
            await run_command('echo "a && b"')

        assert "a && b" in output.getvalue()


async def test_quoted_redirect_not_parsed(temp_db):
    """Test that > inside quotes is not treated as redirect."""
    with SystemContext(user="test_user", fsimage=temp_db) as ctx:
        ctx.mount("sbin", BinProvider())

        output = io.StringIO()
        with ctx.child(stdout=output):
            await run_command('echo "a > b"')

        assert "a > b" in output.getvalue()


async def test_background_command(temp_db):
    """Test & runs command in background."""
    import asyncio

    with SystemContext(user="test_user", fsimage=temp_db) as ctx:
        ctx.mount("sbin", BinProvider())

        await run_command("echo background &")

        # Give the background task a moment to complete
        await asyncio.sleep(0.1)

        # Background task should have been registered
        assert len(ctx._background_tasks) >= 1
