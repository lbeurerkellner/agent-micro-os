"""Tests for _build_cap_snapshot selective workspace export."""

import pytest

from system.execute import _build_cap_snapshot


class FakeFS:
    """Minimal FS stub backed by a dict of {vault_path: bytes}."""

    def __init__(self, files: dict[str, bytes]):
        self._files = files

    def exists(self, path: str) -> bool:
        path = path.strip("/")
        if not path:
            return True
        if path in self._files:
            return True
        # Check if it's a directory prefix
        prefix = path + "/"
        return any(f.startswith(prefix) for f in self._files)

    def is_dir(self, path: str) -> bool:
        path = path.strip("/")
        if not path:
            return True
        if path in self._files:
            return False
        prefix = path + "/"
        return any(f.startswith(prefix) for f in self._files)

    def read(self, path: str) -> bytes:
        path = path.strip("/")
        if path in self._files:
            return self._files[path]
        raise FileNotFoundError(path)

    def list(self, prefix: str = "") -> list[str]:
        prefix = prefix.strip("/")
        if not prefix:
            return list(self._files.keys())
        pfx = prefix + "/"
        return [f for f in self._files if f.startswith(pfx) or f == prefix]


# A vault with realistic structure
VAULT_FILES = {
    "bin/tree": b"# ---\n# description: tree\n# access: ['$@:ro']\n# ---\nprint('tree')\n",
    "bin/greet": b"# ---\n# description: greet\n# ---\nprint('hi')\n",
    "bin/store_experience": b"# ---\n# access: ['/var/experiences:rw']\n# ---\nprint('store')\n",
    "var/experiences/2026-a.md": b"experience a",
    "var/experiences/2026-b.md": b"experience b",
    "var/log/system.log": b"log data",
    "var/sessions/s1.json": b"{}",
    "etc/config.yaml": b"key: val",
    "www/index.html": b"<html></html>",
    "docs/readme.md": b"# readme",
}


@pytest.fixture
def fs():
    return FakeFS(VAULT_FILES)


# -----------------------------------------------------------------------
# Case 1: $@ only
# -----------------------------------------------------------------------


class TestDollarAtOnly:
    """access: ['$@'] or ['$@:ro'] — workspace contains only passed files."""

    def test_single_file_from_root(self, fs):
        snapshot, args = _build_cap_snapshot(
            fs, ["$@:ro"], ("etc/config.yaml",), "/"
        )
        assert set(snapshot.keys()) == {"etc/config.yaml"}
        assert args == ["etc/config.yaml"]

    def test_single_file_from_subdir(self, fs):
        """Running from /bin with a relative path."""
        snapshot, args = _build_cap_snapshot(
            fs, ["$@:ro"], ("greet",), "/bin"
        )
        assert set(snapshot.keys()) == {"bin/greet"}
        assert args == ["bin/greet"]

    def test_directory_arg_from_root(self, fs):
        """Passing a directory includes all files under it."""
        snapshot, args = _build_cap_snapshot(
            fs, ["$@:ro"], ("var/experiences",), "/"
        )
        assert set(snapshot.keys()) == {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
        }
        assert args == ["var/experiences"]

    def test_dot_from_subdir(self, fs):
        """tree . from /bin should include all files under bin/."""
        snapshot, args = _build_cap_snapshot(
            fs, ["$@:ro"], (".",), "/bin"
        )
        assert set(snapshot.keys()) == {
            "bin/tree",
            "bin/greet",
            "bin/store_experience",
        }
        assert args == ["bin"]

    def test_dot_from_root(self, fs):
        """tree . from / should include all vault files."""
        snapshot, args = _build_cap_snapshot(
            fs, ["$@:ro"], (".",), "/"
        )
        assert set(snapshot.keys()) == set(VAULT_FILES.keys())
        assert args == ["."]

    def test_dot_dot_from_subdir(self, fs):
        """.. from /var/experiences should resolve to var/."""
        snapshot, args = _build_cap_snapshot(
            fs, ["$@:ro"], ("..",), "/var/experiences"
        )
        expected = {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
            "var/log/system.log",
            "var/sessions/s1.json",
        }
        assert set(snapshot.keys()) == expected
        assert args == ["var"]

    def test_flags_are_passed_through(self, fs):
        """Flags (starting with -) should not be treated as paths."""
        snapshot, args = _build_cap_snapshot(
            fs, ["$@"], ("-v", "etc/config.yaml", "--long"), "/"
        )
        assert set(snapshot.keys()) == {"etc/config.yaml"}
        assert args == ["-v", "etc/config.yaml", "--long"]

    def test_nonexistent_arg(self, fs):
        """Non-existent paths should be silently skipped in snapshot."""
        snapshot, args = _build_cap_snapshot(
            fs, ["$@"], ("no/such/file",), "/"
        )
        assert snapshot == {}
        assert args == ["no/such/file"]

    def test_multiple_files(self, fs):
        snapshot, args = _build_cap_snapshot(
            fs, ["$@:rw"], ("config.yaml", "../www/index.html"), "/etc"
        )
        assert set(snapshot.keys()) == {"etc/config.yaml", "www/index.html"}
        assert args == ["etc/config.yaml", "www/index.html"]

    def test_no_args(self, fs):
        """No args means empty snapshot."""
        snapshot, args = _build_cap_snapshot(fs, ["$@"], (), "/bin")
        assert snapshot == {}
        assert args == []


# -----------------------------------------------------------------------
# Case 2: Absolute access paths only
# -----------------------------------------------------------------------


class TestAbsoluteAccessOnly:
    """access: ['/var/experiences:rw'] — workspace contains only matched files."""

    def test_directory_access(self, fs):
        snapshot, args = _build_cap_snapshot(
            fs, ["/var/experiences:rw"], (), "/"
        )
        assert set(snapshot.keys()) == {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
        }
        assert args == []

    def test_directory_access_from_different_cwd(self, fs):
        """cwd should not affect explicit access paths."""
        snapshot, args = _build_cap_snapshot(
            fs, ["/var/experiences:rw"], (), "/bin"
        )
        assert set(snapshot.keys()) == {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
        }

    def test_single_file_access(self, fs):
        snapshot, args = _build_cap_snapshot(
            fs, ["/etc/config.yaml:ro"], (), "/"
        )
        assert set(snapshot.keys()) == {"etc/config.yaml"}

    def test_multiple_access_paths(self, fs):
        snapshot, _ = _build_cap_snapshot(
            fs,
            ["/var/experiences:rw", "/etc/config.yaml:ro"],
            (),
            "/",
        )
        assert set(snapshot.keys()) == {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
            "etc/config.yaml",
        }

    def test_no_leakage(self, fs):
        """Only declared paths should appear — no bin/, www/, etc."""
        snapshot, _ = _build_cap_snapshot(
            fs, ["/var/experiences:rw"], (), "/"
        )
        for key in snapshot:
            assert key.startswith("var/experiences/"), f"unexpected file: {key}"

    def test_nonexistent_path(self, fs):
        snapshot, _ = _build_cap_snapshot(
            fs, ["/does/not/exist:rw"], (), "/"
        )
        assert snapshot == {}

    def test_empty_directory(self):
        """Access to an empty directory gives empty snapshot."""
        empty_fs = FakeFS({"var/other/file.txt": b"data"})
        snapshot, _ = _build_cap_snapshot(
            empty_fs, ["/var/empty:rw"], (), "/"
        )
        assert snapshot == {}

    def test_glob_pattern(self, fs):
        """Glob patterns in access should match files."""
        snapshot, _ = _build_cap_snapshot(
            fs, ["/var/experiences/*.md:ro"], (), "/"
        )
        assert set(snapshot.keys()) == {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
        }


# -----------------------------------------------------------------------
# Case 3: Absolute path + $@
# -----------------------------------------------------------------------


class TestMixedAccess:
    """access: ['/var/test:rw', '$@'] — both explicit and arg files."""

    def test_mixed_from_subdir(self, fs):
        """Explicit path + $@ file from /bin."""
        snapshot, args = _build_cap_snapshot(
            fs,
            ["/var/experiences:rw", "$@"],
            ("greet",),
            "/bin",
        )
        assert set(snapshot.keys()) == {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
            "bin/greet",
        }
        # $@ arg should be rewritten to vault-root-relative
        assert args == ["bin/greet"]

    def test_mixed_from_root(self, fs):
        snapshot, args = _build_cap_snapshot(
            fs,
            ["/var/experiences:rw", "$@"],
            ("etc/config.yaml",),
            "/",
        )
        assert set(snapshot.keys()) == {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
            "etc/config.yaml",
        }
        assert args == ["etc/config.yaml"]

    def test_mixed_with_dot(self, fs):
        """$@ with . from /bin + explicit access."""
        snapshot, args = _build_cap_snapshot(
            fs,
            ["/var/log:ro", "$@:ro"],
            (".",),
            "/bin",
        )
        assert "var/log/system.log" in snapshot
        assert "bin/tree" in snapshot
        assert "bin/greet" in snapshot
        # No leakage of other top-level dirs
        assert "etc/config.yaml" not in snapshot
        assert "www/index.html" not in snapshot
        assert args == ["bin"]

    def test_mixed_no_args(self, fs):
        """Mixed access with no $@ args — only explicit paths appear."""
        snapshot, args = _build_cap_snapshot(
            fs,
            ["/var/experiences:rw", "$@"],
            (),
            "/bin",
        )
        assert set(snapshot.keys()) == {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
        }
        assert args == []

    def test_mixed_with_flags(self, fs):
        snapshot, args = _build_cap_snapshot(
            fs,
            ["/etc/config.yaml:ro", "$@:rw"],
            ("-f", "greet", "--verbose"),
            "/bin",
        )
        assert set(snapshot.keys()) == {
            "etc/config.yaml",
            "bin/greet",
        }
        assert args == ["-f", "bin/greet", "--verbose"]

    def test_overlap_deduplication(self, fs):
        """If $@ arg overlaps with explicit path, no duplicates."""
        snapshot, args = _build_cap_snapshot(
            fs,
            ["/var/experiences:rw", "$@"],
            ("../var/experiences/2026-a.md",),
            "/bin",
        )
        # Should contain experiences files (no duplication issues)
        assert "var/experiences/2026-a.md" in snapshot
        assert "var/experiences/2026-b.md" in snapshot
        assert snapshot["var/experiences/2026-a.md"] == b"experience a"


# -----------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:

    def test_empty_access(self, fs):
        """No access entries means empty snapshot."""
        snapshot, args = _build_cap_snapshot(fs, [], ("file.txt",), "/")
        assert snapshot == {}
        assert args == ["file.txt"]

    def test_cwd_root_slash(self, fs):
        """cwd='/' should behave same as cwd=''."""
        s1, a1 = _build_cap_snapshot(fs, ["$@"], ("etc/config.yaml",), "/")
        s2, a2 = _build_cap_snapshot(fs, ["$@"], ("etc/config.yaml",), "")
        assert set(s1.keys()) == set(s2.keys())

    def test_deeply_nested_cwd(self, fs):
        snapshot, args = _build_cap_snapshot(
            fs, ["$@:ro"], ("..",), "/var/experiences"
        )
        assert "var/log/system.log" in snapshot
        assert "var/sessions/s1.json" in snapshot
        assert args == ["var"]

    def test_trailing_slash_in_access(self, fs):
        """Trailing slash on access path should work."""
        snapshot, _ = _build_cap_snapshot(
            fs, ["/var/experiences/:rw"], (), "/"
        )
        assert set(snapshot.keys()) == {
            "var/experiences/2026-a.md",
            "var/experiences/2026-b.md",
        }

    def test_content_preserved(self, fs):
        """Snapshot values should be the actual file contents."""
        snapshot, _ = _build_cap_snapshot(
            fs, ["/etc/config.yaml:ro"], (), "/"
        )
        assert snapshot["etc/config.yaml"] == b"key: val"

    def test_non_path_args_not_rewritten(self, fs):
        """edit_file pattern: only the file arg is a path, rest are strings.

        edit_file test.txt 'world' 'you' — only test.txt should be rewritten,
        'world' and 'you' are search/replace strings, not paths.
        """
        # Add a test file to the vault
        test_fs = FakeFS({**VAULT_FILES, "agent/test.txt": b"hello world"})
        snapshot, args = _build_cap_snapshot(
            test_fs, ["$@:rw"], ("test.txt", "world", "you"), "/agent"
        )
        assert set(snapshot.keys()) == {"agent/test.txt"}
        # Only test.txt is rewritten; 'world' and 'you' are not vault paths
        assert args == ["agent/test.txt", "world", "you"]


# -----------------------------------------------------------------------
# Cap script scenario tests
# -----------------------------------------------------------------------


EDIT_FILE_ACCESS = ["$@:rw"]
STORE_EXPERIENCE_ACCESS = ["/var/experiences:rw"]
MIXED_TOOL_ACCESS = ["/var/experiences:rw", "$@"]


class TestCapScriptScenarios:
    """End-to-end workspace scenarios for realistic cap tools."""

    def test_edit_file_from_subdir(self):
        """edit_file test.txt 'hello' 'goodbye' from /agent."""
        vault = FakeFS({
            "agent/test.txt": b"hello world",
            "agent/other.txt": b"other",
            "bin/edit_file": b"# ---\n# access: ['$@:rw']\n# ---\n",
        })
        snapshot, args = _build_cap_snapshot(
            vault, EDIT_FILE_ACCESS,
            ("test.txt", "hello", "goodbye"), "/agent"
        )
        # Only the target file is in the workspace
        assert set(snapshot.keys()) == {"agent/test.txt"}
        assert snapshot["agent/test.txt"] == b"hello world"
        # Only test.txt is rewritten; search/replace strings untouched
        assert args == ["agent/test.txt", "hello", "goodbye"]

    def test_edit_file_from_root(self):
        """edit_file agent/test.txt 'hello' 'goodbye' from /."""
        vault = FakeFS({"agent/test.txt": b"hello world"})
        snapshot, args = _build_cap_snapshot(
            vault, EDIT_FILE_ACCESS,
            ("agent/test.txt", "hello", "goodbye"), "/"
        )
        assert set(snapshot.keys()) == {"agent/test.txt"}
        assert args == ["agent/test.txt", "hello", "goodbye"]

    def test_edit_file_with_flags(self):
        """edit_file test.txt --search 'hello world' --replace 'bye' from /agent."""
        vault = FakeFS({"agent/test.txt": b"hello world"})
        snapshot, args = _build_cap_snapshot(
            vault, EDIT_FILE_ACCESS,
            ("test.txt", "--search", "hello world", "--replace", "bye"), "/agent"
        )
        assert set(snapshot.keys()) == {"agent/test.txt"}
        assert args == ["agent/test.txt", "--search", "hello world", "--replace", "bye"]

    def test_store_experience_from_root(self):
        """store_experience testing 'some text' from /."""
        vault = FakeFS({
            "var/experiences/old.md": b"old",
            "bin/store_experience": b"script",
        })
        snapshot, args = _build_cap_snapshot(
            vault, STORE_EXPERIENCE_ACCESS,
            ("testing", "some text"), "/"
        )
        # Only experiences dir is exported, not bin/
        assert set(snapshot.keys()) == {"var/experiences/old.md"}
        # Args are not rewritten (no $@ in access)
        assert args == ["testing", "some text"]

    def test_store_experience_from_subdir(self):
        """store_experience from /bin — cwd should not matter."""
        vault = FakeFS({"var/experiences/old.md": b"old"})
        snapshot, args = _build_cap_snapshot(
            vault, STORE_EXPERIENCE_ACCESS,
            ("testing", "text"), "/bin"
        )
        assert set(snapshot.keys()) == {"var/experiences/old.md"}

    def test_store_experience_empty_dir(self):
        """store_experience when /var/experiences is empty."""
        vault = FakeFS({"var/log/app.log": b"log"})
        snapshot, args = _build_cap_snapshot(
            vault, STORE_EXPERIENCE_ACCESS,
            ("testing", "text"), "/"
        )
        # No experiences exist yet — empty workspace is fine,
        # the script will create the file
        assert snapshot == {}

    def test_tree_from_subdir(self):
        """tree . from /bin."""
        vault = FakeFS({
            "bin/tree": b"script",
            "bin/greet": b"script",
            "var/log/app.log": b"log",
        })
        snapshot, args = _build_cap_snapshot(
            vault, ["$@:ro"], (".",), "/bin"
        )
        assert set(snapshot.keys()) == {"bin/tree", "bin/greet"}
        assert "var/log/app.log" not in snapshot
        assert args == ["bin"]

    def test_tree_specific_dir(self):
        """tree var from /."""
        vault = FakeFS({
            "bin/tree": b"script",
            "var/log/app.log": b"log",
            "var/experiences/a.md": b"exp",
        })
        snapshot, args = _build_cap_snapshot(
            vault, ["$@:ro"], ("var",), "/"
        )
        assert set(snapshot.keys()) == {
            "var/log/app.log",
            "var/experiences/a.md",
        }
        assert "bin/tree" not in snapshot
        assert args == ["var"]

    def test_mixed_tool_file_and_experiences(self):
        """A tool with both /var/experiences:rw and $@ from /agent."""
        vault = FakeFS({
            "agent/input.txt": b"data",
            "var/experiences/old.md": b"old",
            "bin/sometool": b"script",
        })
        snapshot, args = _build_cap_snapshot(
            vault, MIXED_TOOL_ACCESS,
            ("input.txt",), "/agent"
        )
        assert set(snapshot.keys()) == {
            "agent/input.txt",
            "var/experiences/old.md",
        }
        assert "bin/sometool" not in snapshot
        assert args == ["agent/input.txt"]

    def test_mixed_tool_no_file_args(self):
        """Mixed tool with only string args (no files)."""
        vault = FakeFS({
            "var/experiences/old.md": b"old",
            "bin/stuff": b"other",
        })
        snapshot, args = _build_cap_snapshot(
            vault, MIXED_TOOL_ACCESS,
            ("keyword", "some description"), "/"
        )
        # Only explicit access path, string args don't resolve
        assert set(snapshot.keys()) == {"var/experiences/old.md"}
        assert args == ["keyword", "some description"]
