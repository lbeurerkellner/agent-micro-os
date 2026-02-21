"""Test cases for grep command."""

import io

from system.context import SystemContext
from bin import grep


# ---------------------------------------------------------------------------
# Basic matching
# ---------------------------------------------------------------------------

async def test_grep_basic_match(temp_db):
    """Test basic string matching in a single file."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"hello world\nfoo bar\nhello again\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("hello", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "hello world" in lines[0]
        assert "hello again" in lines[1]


async def test_grep_no_match(temp_db):
    """Test grep with no matching lines."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"hello world\nfoo bar\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("xyz", "file.txt")
        assert output.getvalue().strip() == ""


async def test_grep_regex(temp_db):
    """Test grep with regex patterns."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"foo123\nbar456\nfoo789\nbaz\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("foo[0-9]+", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "foo123" in lines[0]
        assert "foo789" in lines[1]


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

async def test_grep_case_insensitive(temp_db):
    """Test grep with -i flag."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"Hello World\nhello world\nHELLO WORLD\nfoo\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-i", "hello", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 3


async def test_grep_invert_match(temp_db):
    """Test grep with -v flag (invert match)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"hello\nworld\nhello again\nfoo\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-v", "hello", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "world" in lines[0]
        assert "foo" in lines[1]


async def test_grep_line_numbers(temp_db):
    """Test grep with -n flag shows line numbers."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"aaa\nbbb\nccc\nbbb\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-n", "bbb", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "2:" in lines[0]
        assert "4:" in lines[1]


async def test_grep_count(temp_db):
    """Test grep with -c flag (count mode)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"hello\nworld\nhello again\nhello third\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-c", "hello", "file.txt")
        result = output.getvalue().strip()
        assert result == "3"


async def test_grep_files_with_matches(temp_db):
    """Test grep with -l flag (list matching files)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"hello world\n")
        vault.write("b.txt", b"foo bar\n")
        vault.write("c.txt", b"hello again\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-l", "hello", "a.txt", "b.txt", "c.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "a.txt" in lines
        assert "c.txt" in lines


async def test_grep_files_without_matches(temp_db):
    """Test grep with -L flag (list non-matching files)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"hello world\n")
        vault.write("b.txt", b"foo bar\n")
        vault.write("c.txt", b"hello again\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-L", "hello", "a.txt", "b.txt", "c.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 1
        assert "b.txt" in lines[0]


async def test_grep_fixed_strings(temp_db):
    """Test grep with -F flag (fixed string, no regex)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"foo.bar\nfoo*bar\nfooXbar\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-F", "foo.bar", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 1
        assert "foo.bar" in lines[0]


async def test_grep_whole_word(temp_db):
    """Test grep with -w flag (whole word matching)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"cat\ncatch\nthe cat sat\ncatalog\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-w", "cat", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "cat" in lines[0]
        assert "the cat sat" in lines[1]


async def test_grep_whole_line(temp_db):
    """Test grep with -x flag (whole line matching)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"hello\nhello world\nworld\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-x", "hello", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 1
        assert lines[0].rstrip() == "hello"


async def test_grep_max_count(temp_db):
    """Test grep with -m flag (max count per file)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"aaa\nbbb\naaa\nbbb\naaa\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-m", "2", "aaa", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2


async def test_grep_only_matching(temp_db):
    """Test grep with -o flag (only matching parts)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"foo123bar\nhello456world\nnothing\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-o", "[0-9]+", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "123" in lines[0]
        assert "456" in lines[1]


async def test_grep_quiet_mode(temp_db):
    """Test grep with -q flag produces no output."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"hello world\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-q", "hello", "file.txt")
        assert output.getvalue() == ""


# ---------------------------------------------------------------------------
# Filename display
# ---------------------------------------------------------------------------

async def test_grep_multiple_files_shows_filename(temp_db):
    """Test that grep shows filenames when searching multiple files."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"hello\n")
        vault.write("b.txt", b"hello\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("hello", "a.txt", "b.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "a.txt:" in lines[0]
        assert "b.txt:" in lines[1]


async def test_grep_single_file_no_filename(temp_db):
    """Test that grep hides filename for single file by default."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"hello\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("hello", "file.txt")
        result = output.getvalue().strip()
        assert result == "hello"


async def test_grep_force_filename(temp_db):
    """Test grep with -H flag forces filename display."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"hello\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-H", "hello", "file.txt")
        result = output.getvalue().strip()
        assert "file.txt:" in result


async def test_grep_suppress_filename(temp_db):
    """Test grep with -h flag suppresses filename."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"hello\n")
        vault.write("b.txt", b"hello\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-h", "hello", "a.txt", "b.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert all(":" not in line for line in lines)


async def test_grep_line_number_with_filename(temp_db):
    """Test -n with multiple files shows filepath:lineno:line."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"foo\nhello\n")
        vault.write("b.txt", b"hello\nbar\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-n", "hello", "a.txt", "b.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "a.txt:2:" in lines[0]
        assert "b.txt:1:" in lines[1]


async def test_grep_count_multiple_files(temp_db):
    """Test -c with multiple files shows filename:count."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"hello\nhello\n")
        vault.write("b.txt", b"world\n")
        vault.write("c.txt", b"hello\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-c", "hello", "a.txt", "b.txt", "c.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 3
        assert "a.txt:2" in lines[0]
        assert "b.txt:0" in lines[1]
        assert "c.txt:1" in lines[2]


# ---------------------------------------------------------------------------
# Recursive search
# ---------------------------------------------------------------------------

async def test_grep_recursive(temp_db):
    """Test grep with -r flag for recursive search."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"hello world\n")
        vault.write("docs/b.txt", b"hello docs\n")
        vault.write("docs/sub/c.txt", b"hello nested\n")
        vault.write("src/d.txt", b"no match here\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-r", "hello", "/")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 3
        assert any("a.txt" in l for l in lines)
        assert any("b.txt" in l for l in lines)
        assert any("c.txt" in l for l in lines)


async def test_grep_recursive_from_subdirectory(temp_db):
    """Test recursive grep limited to a subdirectory."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"hello root\n")
        vault.write("docs/b.txt", b"hello docs\n")
        vault.write("docs/sub/c.txt", b"hello nested\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-r", "hello", "docs")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert all("hello" in l for l in lines)
        assert not any("a.txt" in l for l in lines)


async def test_grep_recursive_from_cwd(temp_db):
    """Test recursive grep from current working directory."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("project/src/main.py", b"import os\n")
        vault.write("project/src/lib.py", b"import sys\n")
        vault.write("project/docs/readme.md", b"no matches here\n")
        vault.write("other/file.txt", b"import nothing\n")

        ctx.cwd = "/project"
        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-r", "import", ".")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert all("import" in l for l in lines)


# ---------------------------------------------------------------------------
# Context lines (-A, -B, -C)
# ---------------------------------------------------------------------------

async def test_grep_after_context(temp_db):
    """Test grep with -A flag (lines after match)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"line1\nMATCH\nafter1\nafter2\nline5\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-A", "2", "MATCH", "file.txt")
        text = output.getvalue()
        assert "MATCH" in text
        assert "after1" in text
        assert "after2" in text
        assert "line5" not in text


async def test_grep_before_context(temp_db):
    """Test grep with -B flag (lines before match)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"line1\nbefore1\nMATCH\nline4\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-B", "1", "MATCH", "file.txt")
        text = output.getvalue()
        assert "before1" in text
        assert "MATCH" in text
        assert "line1" not in text
        assert "line4" not in text


async def test_grep_context(temp_db):
    """Test grep with -C flag (lines before and after match)."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"a\nb\nc\nMATCH\nd\ne\nf\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-C", "1", "MATCH", "file.txt")
        text = output.getvalue()
        assert "c" in text
        assert "MATCH" in text
        assert "d" in text
        assert "a" not in text
        assert "f" not in text


async def test_grep_context_overlapping_matches(temp_db):
    """Test context lines merge when matches are close together."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"a\nMATCH1\nb\nMATCH2\nc\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-C", "1", "MATCH", "file.txt")
        text = output.getvalue()
        assert "a" in text
        assert "MATCH1" in text
        assert "b" in text
        assert "MATCH2" in text
        assert "c" in text
        # Should NOT have a group separator since ranges overlap
        assert "--" not in text


async def test_grep_context_group_separator(temp_db):
    """Test that non-overlapping context groups are separated by --."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"a\nMATCH1\nb\nc\nd\ne\nMATCH2\nf\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-C", "1", "MATCH", "file.txt")
        text = output.getvalue()
        assert "MATCH1" in text
        assert "MATCH2" in text
        lines = text.strip().splitlines()
        # Groups are far enough apart that a separator should appear
        assert "--" in lines


async def test_grep_context_with_line_numbers(temp_db):
    """Test context lines also get line numbers with -n."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"a\nb\nMATCH\nd\ne\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-n", "-A", "1", "MATCH", "file.txt")
        text = output.getvalue()
        assert "3:" in text  # MATCH line
        assert "4-" in text or "4:" in text  # context line


# ---------------------------------------------------------------------------
# Include / exclude globs
# ---------------------------------------------------------------------------

async def test_grep_include_glob(temp_db):
    """Test grep --include to filter by filename pattern."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.py", b"hello\n")
        vault.write("b.txt", b"hello\n")
        vault.write("c.py", b"hello\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-r", "--include=*.py", "hello", "/")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert all(".py" in l for l in lines)


async def test_grep_exclude_glob(temp_db):
    """Test grep --exclude to skip certain files."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.py", b"hello\n")
        vault.write("b.txt", b"hello\n")
        vault.write("c.py", b"hello\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-r", "--exclude=*.py", "hello", "/")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 1
        assert "b.txt" in lines[0]


# ---------------------------------------------------------------------------
# Multiple patterns (-e)
# ---------------------------------------------------------------------------

async def test_grep_multiple_patterns(temp_db):
    """Test grep with -e for multiple patterns."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"apple\nbanana\ncherry\ndate\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-e", "apple", "-e", "cherry", "file.txt")
        lines = output.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "apple" in lines[0]
        assert "cherry" in lines[1]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

async def test_grep_nonexistent_file(temp_db):
    """Test grep on non-existent file shows error."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("hello", "nonexistent.txt")
        assert "No such file" in output.getvalue()


async def test_grep_directory_without_recursive(temp_db):
    """Test grep on a directory without -r shows error."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("dir/file.txt", b"hello\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("hello", "dir")
        assert "Is a directory" in output.getvalue()


async def test_grep_binary_file(temp_db):
    """Test grep on binary file shows binary match notice."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("binary.bin", b"\x00\x01hello\xff\xfe")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("hello", "binary.bin")
        result = output.getvalue()
        assert "binary" in result.lower()


async def test_grep_empty_file(temp_db):
    """Test grep on empty file produces no output."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("empty.txt", b"")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("hello", "empty.txt")
        assert output.getvalue().strip() == ""


async def test_grep_no_arguments(temp_db):
    """Test grep with no arguments shows usage."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run()
        assert "Usage" in output.getvalue()


async def test_grep_absolute_path(temp_db):
    """Test grep with absolute file path."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("docs/readme.md", b"hello from docs\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("hello", "/docs/readme.md")
        assert "hello from docs" in output.getvalue()


async def test_grep_relative_path_from_cwd(temp_db):
    """Test grep resolves relative paths against cwd."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("project/src/main.py", b"import os\n")

        ctx.cwd = "/project"
        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("import", "src/main.py")
        assert "import os" in output.getvalue()


async def test_grep_combined_flags(temp_db):
    """Test combining -i and -c flags."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("file.txt", b"Hello\nWORLD\nhello\nfoo\n")

        output = io.StringIO()
        with ctx.child(stdout=output):
            await grep.run("-i", "-c", "hello", "file.txt")
        result = output.getvalue().strip()
        assert result == "2"


# ---------------------------------------------------------------------------
# _grep_files helper (for system/tools.py)
# ---------------------------------------------------------------------------

async def test_grep_helper_returns_results(temp_db):
    """Test _grep_files helper returns structured results."""
    with SystemContext(user="grep_user", fsimage=temp_db) as ctx:
        vault = ctx.fs()
        vault.write("a.txt", b"hello world\nfoo bar\n")
        vault.write("b.txt", b"hello again\n")

        results = grep._grep_files(vault, "hello", ["a.txt", "b.txt"])
        assert len(results) == 2
        assert results[0][0] == "a.txt"
        assert results[0][1] == 1
        assert "hello world" in results[0][2]
        assert results[1][0] == "b.txt"
        assert results[1][1] == 1
        assert "hello again" in results[1][2]
