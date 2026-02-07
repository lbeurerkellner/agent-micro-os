"""Test ash -c command chaining functionality."""

import io
from contextlib import redirect_stdout

from system.context import SystemContext
from fs.providers import BinProvider
from bin.ash import run_command


async def test_cd_and_cat_chain(temp_db):
    """Test that cd && cat works correctly."""
    with SystemContext(user="test_user", fsimage=temp_db):
        ctx = SystemContext.current()
        ctx.mount("sbin", BinProvider())
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"This is the BRAIN.md file in agent directory\n")
        vault.write("README.md", b"This is the root README\n")

        assert vault.exists("agent/BRAIN.md")

        output = io.StringIO()
        with redirect_stdout(output):
            await run_command("cd agent && cat BRAIN.md")

        result = output.getvalue()
        assert "No such file" not in result, f"Got 'No such file' error: {result}"
        assert "BRAIN.md" in result or "agent directory" in result, f"Expected file content, got: {result}"
