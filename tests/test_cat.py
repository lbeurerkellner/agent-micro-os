"""Test cases for cat command."""

import io

from system.context import SystemContext
from bin import cat


async def test_cat_single_file(temp_db):
    """Test cat a single file."""
    with SystemContext(user="cat_test_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file1.txt", b"Hello, World!")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("file1.txt")
        assert "Hello, World!" in output.getvalue()


async def test_cat_multiple_files(temp_db):
    """Test cat multiple files."""
    with SystemContext(user="cat_test_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file1.txt", b"Hello, World!")
        vault.write("file2.txt", b"Second file content\nWith multiple lines\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("file1.txt", "file2.txt")
        result = output.getvalue()
        assert "Hello, World!" in result
        assert "Second file content" in result


async def test_cat_absolute_path(temp_db):
    """Test cat with absolute path."""
    with SystemContext(user="cat_test_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/nested.txt", b"Nested file content")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("/docs/nested.txt")
        assert "Nested file content" in output.getvalue()


async def test_cat_relative_path(temp_db):
    """Test cat with relative path from different directory."""
    with SystemContext(user="cat_test_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/nested.txt", b"Nested file content")

        ctx.cwd = "/docs"
        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("nested.txt")
        assert "Nested file content" in output.getvalue()


async def test_cat_nonexistent_file(temp_db):
    """Test cat non-existent file shows error."""
    with SystemContext(user="cat_test_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("nonexistent.txt")
        assert "No such file" in output.getvalue()


async def test_cat_directory(temp_db):
    """Test cat a directory shows error."""
    with SystemContext(user="cat_test_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/file.txt", b"content")

        ctx.cwd = "/"
        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("/docs")
        assert "Is a directory" in output.getvalue()


async def test_cat_no_arguments(temp_db):
    """Test cat with no arguments shows usage."""
    with SystemContext(user="cat_test_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run()
        assert "Usage" in output.getvalue()


async def test_cat_glob_in_cwd(temp_db):
    """Test cat with a glob pattern matching files in cwd."""
    with SystemContext(user="cat_glob_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"Alpha")
        vault.write("b.txt", b"Beta")
        vault.write("skip.py", b"skip")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("*.txt")
        result = output.getvalue()
        assert "Alpha" in result
        assert "Beta" in result
        assert "skip" not in result


async def test_cat_glob_in_subdirectory(temp_db):
    """Test cat with a glob pattern scoped to a subdirectory."""
    with SystemContext(user="cat_glob_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/a.txt", b"DocA")
        vault.write("docs/b.txt", b"DocB")
        vault.write("root.txt", b"Root")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("docs/*.txt")
        result = output.getvalue()
        assert "DocA" in result
        assert "DocB" in result
        assert "Root" not in result


async def test_cat_glob_no_match(temp_db):
    """Test cat glob that matches nothing prints an error."""
    with SystemContext(user="cat_glob_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"content")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("*.py")
        result = output.getvalue()
        assert "no matches" in result.lower() or "*.py" in result


async def test_cat_binary_file(temp_db):
    """Test cat with binary files."""
    with SystemContext(user="cat_binary_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        binary_data = b"\x00\x01\x02\xff\xfe\x00\x00\x42"
        vault.write("binary.bin", binary_data)

        output = io.StringIO()
        with ctx.child(stdout=output):
            await cat.run("binary.bin")
        result = output.getvalue()
        assert "binary data" in result.lower() or str(len(binary_data)) in result
