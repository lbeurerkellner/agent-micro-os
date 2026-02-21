"""Test cases for rm command."""

import io

from system.context import SystemContext
from bin import rm


async def test_rm_single_file(temp_db):
    """Test removing a single file."""
    with SystemContext(user="rm_test_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file1.txt", b"File 1")
        vault.write("file2.txt", b"File 2")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("file1.txt")
        assert "file1.txt" not in vault.list()
        assert "file2.txt" in vault.list()


async def test_rm_multiple_files(temp_db):
    """Test removing multiple files."""
    with SystemContext(user="rm_test_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file1.txt", b"File 1")
        vault.write("file2.txt", b"File 2")
        vault.write("file3.txt", b"File 3")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("file2.txt", "file3.txt")
        assert "file2.txt" not in vault.list()
        assert "file3.txt" not in vault.list()
        assert "file1.txt" in vault.list()


async def test_rm_nonexistent(temp_db):
    """Test removing non-existent file shows error."""
    with SystemContext(user="rm_test_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("nonexistent.txt")
        result = output.getvalue()
        assert "No such file" in result or "cannot remove" in result.lower()


async def test_rm_no_arguments(temp_db):
    """Test rm with no arguments shows usage."""
    with SystemContext(user="rm_test_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run()
        result = output.getvalue()
        assert "Usage" in result or "usage" in result


async def test_rm_directory_without_flag(temp_db):
    """Test removing directory without -r fails."""
    with SystemContext(user="rm_dir_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/file1.txt", b"Doc 1")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("docs")
        result = output.getvalue()
        assert "is a directory" in result.lower() or "cannot remove" in result.lower()
        assert "docs/file1.txt" in vault.list()


async def test_rm_directory_recursive(temp_db):
    """Test removing directory with -r flag."""
    with SystemContext(user="rm_dir_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/file1.txt", b"Doc 1")
        vault.write("docs/file2.txt", b"Doc 2")
        vault.write("docs/subdir/nested.txt", b"Nested")
        vault.write("other.txt", b"Other")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("-r", "docs")
        assert "docs/file1.txt" not in vault.list()
        assert "docs/file2.txt" not in vault.list()
        assert "docs/subdir/nested.txt" not in vault.list()
        assert "other.txt" in vault.list()


async def test_rm_recursive_multiple(temp_db):
    """Test removing multiple items with -r."""
    with SystemContext(user="rm_dir_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("dir1/a.txt", b"A")
        vault.write("dir2/b.txt", b"B")
        vault.write("file.txt", b"File")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("-r", "dir1", "dir2", "file.txt")
        assert "dir1/a.txt" not in vault.list()
        assert "dir2/b.txt" not in vault.list()
        assert "file.txt" not in vault.list()


async def test_rm_recursive_nonexistent(temp_db):
    """Test rm -r on non-existent directory."""
    with SystemContext(user="rm_dir_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("-r", "nonexistent")
        result = output.getvalue()
        assert "No such file" in result or "cannot remove" in result.lower()


async def test_rm_absolute_path(temp_db):
    """Test rm with absolute path."""
    with SystemContext(user="rm_path_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/file.txt", b"Content")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("/docs/file.txt")
        assert "docs/file.txt" not in vault.list()


async def test_rm_relative_path(temp_db):
    """Test rm with relative path from different directory."""
    with SystemContext(user="rm_path_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/nested/deep.txt", b"Deep")

        ctx.cwd = "/docs"
        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("nested/deep.txt")
        assert "docs/nested/deep.txt" not in vault.list()


async def test_rm_recursive_absolute_subdirectory(temp_db):
    """Test rm -r with absolute path on subdirectory."""
    with SystemContext(user="rm_path_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("project/src/main.py", b"Main")
        vault.write("project/src/util.py", b"Util")
        vault.write("project/readme.txt", b"Readme")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("-r", "/project/src")
        assert "project/src/main.py" not in vault.list()
        assert "project/src/util.py" not in vault.list()
        assert "project/readme.txt" in vault.list()


async def test_rm_glob_all_txt_in_cwd(temp_db):
    """Test rm with glob pattern matching all .txt files in cwd."""
    with SystemContext(user="rm_glob_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"A")
        vault.write("b.txt", b"B")
        vault.write("keep.py", b"keep")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("*.txt")
        assert "a.txt" not in vault.list()
        assert "b.txt" not in vault.list()
        assert "keep.py" in vault.list()


async def test_rm_glob_in_subdirectory(temp_db):
    """Test rm with glob pattern scoped to a subdirectory."""
    with SystemContext(user="rm_glob_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/a.txt", b"A")
        vault.write("docs/b.txt", b"B")
        vault.write("docs/keep.md", b"keep")
        vault.write("root.txt", b"root")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("docs/*.txt")
        assert "docs/a.txt" not in vault.list()
        assert "docs/b.txt" not in vault.list()
        assert "docs/keep.md" in vault.list()
        assert "root.txt" in vault.list()


async def test_rm_glob_from_cwd(temp_db):
    """Test rm glob pattern resolved relative to cwd."""
    with SystemContext(user="rm_glob_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("src/foo.py", b"foo")
        vault.write("src/bar.py", b"bar")
        vault.write("src/readme.txt", b"readme")

        ctx.cwd = "/src"
        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("*.py")
        assert "src/foo.py" not in vault.list()
        assert "src/bar.py" not in vault.list()
        assert "src/readme.txt" in vault.list()


async def test_rm_glob_no_match(temp_db):
    """Test rm glob that matches nothing prints an error."""
    with SystemContext(user="rm_glob_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"content")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("*.py")
        result = output.getvalue()
        assert "no matches" in result.lower() or "*.py" in result
        assert "file.txt" in vault.list()


async def test_rm_permanent_deletion(temp_db):
    """Test that rm permanently deletes all versions."""
    with SystemContext(user="rm_permanent_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("versioned.txt", b"Version 1")
        vault.write("versioned.txt", b"Version 2")
        vault.write("versioned.txt", b"Version 3")

        log = vault.log("versioned.txt")
        assert len(log) == 3

        output = io.StringIO()
        with ctx.child(stdout=output):
            await rm.run("versioned.txt")
        assert "versioned.txt" not in vault.list()

        try:
            vault.log("versioned.txt")
            assert False, "log() should raise FileNotFoundError"
        except FileNotFoundError:
            pass
