"""Test cases for cat command."""

import io
from contextlib import redirect_stdout

from system.context import SystemContext
from bin import cat


async def test_cat_single_file(temp_db):
    """Test cat a single file."""
    with SystemContext(user="cat_test_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("file1.txt", b"Hello, World!")

        output = io.StringIO()
        with redirect_stdout(output):
            await cat.run("file1.txt")
        assert "Hello, World!" in output.getvalue()


async def test_cat_multiple_files(temp_db):
    """Test cat multiple files."""
    with SystemContext(user="cat_test_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("file1.txt", b"Hello, World!")
        vault.write("file2.txt", b"Second file content\nWith multiple lines\n")

        output = io.StringIO()
        with redirect_stdout(output):
            await cat.run("file1.txt", "file2.txt")
        result = output.getvalue()
        assert "Hello, World!" in result
        assert "Second file content" in result


async def test_cat_absolute_path(temp_db):
    """Test cat with absolute path."""
    with SystemContext(user="cat_test_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("docs/nested.txt", b"Nested file content")

        output = io.StringIO()
        with redirect_stdout(output):
            await cat.run("/docs/nested.txt")
        assert "Nested file content" in output.getvalue()


async def test_cat_relative_path(temp_db):
    """Test cat with relative path from different directory."""
    with SystemContext(user="cat_test_user", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()
        vault.write("docs/nested.txt", b"Nested file content")

        ctx.cwd = "/docs"
        output = io.StringIO()
        with redirect_stdout(output):
            await cat.run("nested.txt")
        assert "Nested file content" in output.getvalue()


async def test_cat_nonexistent_file(temp_db):
    """Test cat non-existent file shows error."""
    with SystemContext(user="cat_test_user", fsimage=temp_db):
        output = io.StringIO()
        with redirect_stdout(output):
            await cat.run("nonexistent.txt")
        assert "No such file" in output.getvalue()


async def test_cat_directory(temp_db):
    """Test cat a directory shows error."""
    with SystemContext(user="cat_test_user", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()
        vault.write("docs/file.txt", b"content")

        ctx.cwd = "/"
        output = io.StringIO()
        with redirect_stdout(output):
            await cat.run("/docs")
        assert "Is a directory" in output.getvalue()


async def test_cat_no_arguments(temp_db):
    """Test cat with no arguments shows usage."""
    with SystemContext(user="cat_test_user", fsimage=temp_db):
        output = io.StringIO()
        with redirect_stdout(output):
            await cat.run()
        assert "Usage" in output.getvalue()


async def test_cat_binary_file(temp_db):
    """Test cat with binary files."""
    with SystemContext(user="cat_binary_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        binary_data = b"\x00\x01\x02\xff\xfe\x00\x00\x42"
        vault.write("binary.bin", binary_data)

        output = io.StringIO()
        with redirect_stdout(output):
            await cat.run("binary.bin")
        result = output.getvalue()
        assert "binary data" in result.lower() or str(len(binary_data)) in result
