"""Test cases for find command."""

import io
from contextlib import redirect_stdout

from system.context import SystemContext
from bin import find


async def test_find_from_root(temp_db):
    """Test find lists all files recursively from root."""
    with SystemContext(user="find_test_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("file1.txt", b"A")
        vault.write("docs/readme.md", b"B")
        vault.write("docs/notes/todo.txt", b"C")
        vault.write("src/main.py", b"D")

        output = io.StringIO()
        with redirect_stdout(output):
            await find.run()
        result = output.getvalue().strip().splitlines()
        assert "./docs/notes/todo.txt" in result
        assert "./docs/readme.md" in result
        assert "./file1.txt" in result
        assert "./src/main.py" in result
        assert len(result) == 4


async def test_find_from_subdirectory(temp_db):
    """Test find lists files recursively from a subdirectory."""
    with SystemContext(user="find_sub_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("docs/readme.md", b"A")
        vault.write("docs/guides/setup.md", b"B")
        vault.write("docs/guides/advanced/config.md", b"C")
        vault.write("src/main.py", b"D")

        output = io.StringIO()
        with redirect_stdout(output):
            await find.run("docs")
        result = output.getvalue().strip().splitlines()
        assert "docs/guides/advanced/config.md" in result
        assert "docs/guides/setup.md" in result
        assert "docs/readme.md" in result
        assert len(result) == 3


async def test_find_absolute_path(temp_db):
    """Test find with absolute path argument."""
    with SystemContext(user="find_sub_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("docs/guides/setup.md", b"B")
        vault.write("docs/guides/advanced/config.md", b"C")

        output = io.StringIO()
        with redirect_stdout(output):
            await find.run("/docs/guides")
        result = output.getvalue().strip().splitlines()
        assert "docs/guides/advanced/config.md" in result
        assert "docs/guides/setup.md" in result
        assert len(result) == 2


async def test_find_relative_to_cwd(temp_db):
    """Test find resolves relative paths against cwd."""
    with SystemContext(user="find_cwd_user", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()
        vault.write("project/src/main.py", b"A")
        vault.write("project/src/lib/utils.py", b"B")
        vault.write("project/docs/readme.md", b"C")
        vault.write("other/file.txt", b"D")

        ctx.cwd = "/project"
        output = io.StringIO()
        with redirect_stdout(output):
            await find.run()
        result = output.getvalue().strip().splitlines()
        assert "./docs/readme.md" in result
        assert "./src/lib/utils.py" in result
        assert "./src/main.py" in result
        assert len(result) == 3


async def test_find_relative_path_from_cwd(temp_db):
    """Test find with relative path from cwd."""
    with SystemContext(user="find_cwd_user", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()
        vault.write("project/src/main.py", b"A")
        vault.write("project/src/lib/utils.py", b"B")
        vault.write("project/docs/readme.md", b"C")

        ctx.cwd = "/project"
        output = io.StringIO()
        with redirect_stdout(output):
            await find.run("src")
        result = output.getvalue().strip().splitlines()
        assert "src/lib/utils.py" in result
        assert "src/main.py" in result
        assert len(result) == 2


async def test_find_empty_directory(temp_db):
    """Test find on a non-existent directory."""
    with SystemContext(user="find_empty_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("file.txt", b"A")

        output = io.StringIO()
        with redirect_stdout(output):
            await find.run("nonexistent")
        result = output.getvalue().strip()
        assert result == ""


async def test_find_sorted_output(temp_db):
    """Test that find output is sorted."""
    with SystemContext(user="find_sort_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("z.txt", b"Z")
        vault.write("a.txt", b"A")
        vault.write("m/b.txt", b"B")
        vault.write("m/a.txt", b"A")

        output = io.StringIO()
        with redirect_stdout(output):
            await find.run()
        result = output.getvalue().strip().splitlines()
        assert result == sorted(result)
