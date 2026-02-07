"""Test cases for ash shell commands (ls and cd)."""

from system.context import SystemContext
from bin import ls, cd
from bin.ls import _list_directory


async def test_ls_root(temp_db):
    """Test listing root directory."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"brain content")
        vault.write("docs/readme.md", b"readme")

        entries = _list_directory(vault, ctx.cwd)
        assert len(entries) > 0, "Root directory should not be empty"
        assert "agent/" in entries
        assert "docs/" in entries


async def test_exists_and_is_dir(temp_db):
    """Test exists() and is_dir() on files and directories."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"brain content")

        assert vault.exists("agent")
        assert vault.is_dir("agent")
        assert vault.exists("agent/BRAIN.md")
        assert not vault.is_dir("agent/BRAIN.md")


async def test_cd_and_ls(temp_db):
    """Test changing directory and listing."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"brain content")

        ctx.cwd = "/agent"
        assert ctx.cwd == "/agent"

        entries = _list_directory(vault, ctx.cwd)
        assert "BRAIN.md" in entries


async def test_cd_back_to_root(temp_db):
    """Test cd back to root."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"brain content")

        ctx.cwd = "/agent"
        ctx.cwd = "/"
        assert ctx.cwd == "/"

        entries = _list_directory(vault, ctx.cwd)
        assert "agent/" in entries


async def test_ls_command(temp_db):
    """Test ls command execution."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"brain content")
        vault.write("docs/readme.md", b"readme")

        await ls.run()


async def test_cd_command(temp_db):
    """Test cd command with various paths."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"brain content")
        vault.write("docs/tutorials/intro.md", b"intro")

        await cd.run("agent")
        assert ctx.cwd == "/agent"

        await cd.run("/")
        assert ctx.cwd == "/"


async def test_cd_to_file_fails(temp_db):
    """Test that cd into a file doesn't change cwd."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"brain content")

        await cd.run("agent")
        old_cwd = ctx.cwd
        await cd.run("BRAIN.md")
        assert ctx.cwd == old_cwd


async def test_cd_absolute_path(temp_db):
    """Test cd with absolute path."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"brain content")

        await cd.run("/agent")
        assert ctx.cwd == "/agent"


async def test_cd_nonexistent_fails(temp_db):
    """Test cd to non-existent directory."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("agent/BRAIN.md", b"brain content")

        old_cwd = ctx.cwd
        await cd.run("/nonexistent")
        assert ctx.cwd == old_cwd


async def test_cd_nested_and_parent(temp_db):
    """Test cd into nested directory and back with '..'."""
    with SystemContext(user="bob", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()

        vault.write("docs/tutorials/intro.md", b"intro")

        await cd.run("/docs")
        assert ctx.cwd == "/docs"

        await cd.run("tutorials")
        assert ctx.cwd == "/docs/tutorials"

        await cd.run("..")
        assert ctx.cwd == "/docs"
