"""Test cases for ash tab completion."""

from system.context import SystemContext
from fs.providers import BinProvider
from bin.ash import get_available_commands, get_path_completions


def test_command_completion(temp_db):
    """Test command name completion."""
    with SystemContext(user="cmd_user", fsimage=temp_db):
        SystemContext.current().mount("sbin", BinProvider())
        commands = get_available_commands()

        assert "ls" in commands
        assert "cd" in commands
        assert "cat" in commands
        assert "exit" in commands


def test_path_completion_files(temp_db):
    """Test path completion for files in current directory."""
    with SystemContext(user="completion_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("file1.txt", b"content1")
        vault.write("file2.txt", b"content2")
        vault.write("foo.txt", b"foo")
        vault.write("docs/readme.md", b"readme")

        completions = get_path_completions("fi", "/", vault)
        assert "file1.txt" in completions
        assert "file2.txt" in completions
        assert "foo.txt" not in completions


def test_path_completion_directory(temp_db):
    """Test path completion for directories."""
    with SystemContext(user="completion_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("docs/readme.md", b"readme")

        completions = get_path_completions("do", "/", vault)
        assert "docs/" in completions


def test_path_completion_all(temp_db):
    """Test path completion with empty prefix returns all entries."""
    with SystemContext(user="completion_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("file1.txt", b"content1")
        vault.write("file2.txt", b"content2")
        vault.write("foo.txt", b"foo")
        vault.write("docs/readme.md", b"readme")

        completions = get_path_completions("", "/", vault)
        assert "file1.txt" in completions
        assert "file2.txt" in completions
        assert "foo.txt" in completions
        assert "docs/" in completions


def test_path_completion_nested(temp_db):
    """Test nested path completion like 'docs/g'."""
    with SystemContext(user="nested_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("docs/readme.md", b"readme")
        vault.write("docs/guide.md", b"guide")
        vault.write("docs/tutorials/intro.md", b"intro")
        vault.write("docs/tutorials/advanced.md", b"advanced")

        completions = get_path_completions("docs/g", "/", vault)
        assert "docs/guide.md" in completions
        assert "docs/readme.md" not in completions


def test_path_completion_nested_directory(temp_db):
    """Test nested directory completion."""
    with SystemContext(user="nested_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("docs/tutorials/intro.md", b"intro")

        completions = get_path_completions("docs/t", "/", vault)
        assert "docs/tutorials/" in completions


def test_path_completion_deeply_nested(temp_db):
    """Test deeply nested path completion."""
    with SystemContext(user="nested_user", fsimage=temp_db):
        vault = SystemContext.current().fs()
        vault.write("docs/tutorials/intro.md", b"intro")
        vault.write("docs/tutorials/advanced.md", b"advanced")

        completions = get_path_completions("docs/tutorials/a", "/", vault)
        assert "docs/tutorials/advanced.md" in completions
        assert "docs/tutorials/intro.md" not in completions


def test_path_completion_absolute(temp_db):
    """Test absolute path completion."""
    with SystemContext(user="absolute_user", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()
        vault.write("docs/file1.txt", b"content")
        vault.write("docs/file2.txt", b"content")

        ctx.cwd = "/somewhere"

        completions = get_path_completions("/docs/fi", "/somewhere", vault)
        assert "/docs/file1.txt" in completions
        assert "/docs/file2.txt" in completions


def test_path_completion_absolute_directory(temp_db):
    """Test absolute directory completion."""
    with SystemContext(user="absolute_user", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()
        vault.write("docs/file1.txt", b"content")

        completions = get_path_completions("/do", "/somewhere", vault)
        assert "/docs/" in completions


def test_path_completion_relative_from_cwd(temp_db):
    """Test relative path completion from non-root directory."""
    with SystemContext(user="relative_user", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()
        vault.write("docs/readme.md", b"readme")
        vault.write("docs/guide.md", b"guide")
        vault.write("docs/tutorials/intro.md", b"intro")

        ctx.cwd = "/docs"

        completions = get_path_completions("g", "/docs", vault)
        assert "guide.md" in completions
        assert "readme.md" not in completions


def test_path_completion_relative_subdirectory(temp_db):
    """Test relative subdirectory completion from non-root cwd."""
    with SystemContext(user="relative_user", fsimage=temp_db):
        ctx = SystemContext.current()
        vault = ctx.fs()
        vault.write("docs/tutorials/intro.md", b"intro")

        ctx.cwd = "/docs"

        completions = get_path_completions("tutorials/i", "/docs", vault)
        assert "tutorials/intro.md" in completions
