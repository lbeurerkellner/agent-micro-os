"""Tests for .ACCESS directive parsing, export filtering, and commit-back validation."""

from fs.vault import Vault
from bin.sandbox import _build_snapshot, _diff_and_commit, _glob_match
from system.context import SystemContext
from fs.providers import BinProvider


# ── Parsing ──────────────────────────────────────────────────────────────────

async def test_parse_access_rw(temp_db):
    """Plain .ACCESS lines are parsed as read-write."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.fs().write("etc/model/default", b"echo echo")

        from system.program import parse
        program = parse(".ACCESS src/**\n.PROMPT\nDo it\n")
        assert program.access == [("src/**", "rw")]


async def test_parse_access_ro(temp_db):
    """.ACCESS with :ro suffix is parsed as read-only."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.fs().write("etc/model/default", b"echo echo")

        from system.program import parse
        program = parse(".ACCESS src/**\n.ACCESS lib/**:ro\n.PROMPT\nDo it\n")
        assert program.access == [("src/**", "rw"), ("lib/**", "ro")]


async def test_parse_access_dollar_at(temp_db):
    """.ACCESS $@ is stored raw for later expansion."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.fs().write("etc/model/default", b"echo echo")

        from system.program import parse
        program = parse(".ACCESS $@\n.ACCESS lib/**:ro\n.PROMPT\nDo it\n")
        assert program.access == [("$@", "rw"), ("lib/**", "ro")]


async def test_parse_access_dollar_at_ro(temp_db):
    """.ACCESS $@:ro stores $@ with read-only mode."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.fs().write("etc/model/default", b"echo echo")

        from system.program import parse
        program = parse(".ACCESS $@:ro\n.PROMPT\nDo it\n")
        assert program.access == [("$@", "ro")]


async def test_parse_no_access_is_none(temp_db):
    """Programs without .ACCESS have access=None (unrestricted)."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        ctx.mount("sbin", BinProvider())
        ctx.fs().write("etc/model/default", b"echo echo")

        from system.program import parse
        program = parse(".PROMPT\nDo it\n")
        assert program.access is None


# ── resolve_access ───────────────────────────────────────────────────────────

async def test_resolve_access_expands_paths(temp_db):
    """$@ entries expand to vault paths from args."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        vault = ctx.fs()
        vault.write("src/foo.py", b"content")
        vault.write("src/bar.py", b"content")

        from system.program import resolve_access
        access = [("$@", "rw"), ("lib/**", "ro")]
        resolved = resolve_access(access, ("src/foo.py", "src/bar.py"), vault)
        assert ("src/foo.py", "rw") in resolved
        assert ("src/bar.py", "rw") in resolved
        assert ("lib/**", "ro") in resolved


async def test_resolve_access_skips_nonexistent(temp_db):
    """$@ expansion skips args that don't resolve to vault paths."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        vault = ctx.fs()
        vault.write("src/foo.py", b"content")

        from system.program import resolve_access
        access = [("$@", "rw")]
        resolved = resolve_access(access, ("src/foo.py", "nonexistent.py"), vault)
        assert ("src/foo.py", "rw") in resolved
        assert len([g for g, _ in resolved if "nonexistent" in g]) == 0


async def test_resolve_access_skips_flags(temp_db):
    """$@ expansion skips args starting with -."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        vault = ctx.fs()
        vault.write("src/foo.py", b"content")

        from system.program import resolve_access
        access = [("$@", "rw")]
        resolved = resolve_access(access, ("--verbose", "src/foo.py"), vault)
        assert len(resolved) == 1
        assert ("src/foo.py", "rw") in resolved


async def test_resolve_access_none_passthrough(temp_db):
    """resolve_access with None returns None."""
    with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
        from system.program import resolve_access
        assert resolve_access(None, (), ctx.fs()) is None


# ── Export filtering ─────────────────────────────────────────────────────────

class TestExportAccessFiltering:
    """_build_snapshot should only include files matching access globs."""

    def test_access_filters_export(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("src/app.py", b"app code")
        vault.write("lib/util.py", b"util code")
        vault.write("secret/keys.txt", b"top secret")

        access = [("src/**", "rw"), ("lib/**", "ro")]
        snapshot = _build_snapshot(vault, "", access=access)

        assert "src/app.py" in snapshot
        assert "lib/util.py" in snapshot
        assert "secret/keys.txt" not in snapshot

    def test_no_access_exports_all(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("src/app.py", b"app code")
        vault.write("secret/keys.txt", b"top secret")

        snapshot = _build_snapshot(vault, "", access=None)

        assert "src/app.py" in snapshot
        assert "secret/keys.txt" in snapshot

    def test_access_with_prefix(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("project/src/app.py", b"app code")
        vault.write("project/lib/util.py", b"util code")
        vault.write("project/secret/keys.txt", b"top secret")

        access = [("src/**", "rw")]
        snapshot = _build_snapshot(vault, "project", access=access)

        assert "src/app.py" in snapshot
        assert "lib/util.py" not in snapshot
        assert "secret/keys.txt" not in snapshot


# ── Commit-back validation ───────────────────────────────────────────────────

class TestCommitAccessValidation:
    """_diff_and_commit should reject commits with writes outside rw globs."""

    def test_rw_writes_succeed(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("src/app.py", b"original")

        snapshot = {"src/app.py": b"original"}
        current = {"src/app.py": b"modified"}
        access = [("src/**", "rw")]

        _diff_and_commit(vault, snapshot, current, "", access=access)

        # Change should be committed
        assert vault.read("src/app.py") == b"modified"

    def test_ro_writes_rejected(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("src/app.py", b"original")
        vault.write("lib/util.py", b"original")

        snapshot = {"src/app.py": b"original", "lib/util.py": b"original"}
        current = {"src/app.py": b"modified", "lib/util.py": b"modified"}
        access = [("src/**", "rw"), ("lib/**", "ro")]

        _diff_and_commit(vault, snapshot, current, "", access=access)

        # Both changes should be rejected (all-or-nothing)
        assert vault.read("src/app.py") == b"original"
        assert vault.read("lib/util.py") == b"original"

    def test_unlisted_writes_rejected(self, temp_db):
        vault = Vault(temp_db, "tester")

        snapshot = {}
        current = {"src/app.py": b"new file", "hack/evil.py": b"bad stuff"}
        access = [("src/**", "rw")]

        _diff_and_commit(vault, snapshot, current, "", access=access)

        # hack/evil.py is outside access → entire commit rejected
        assert not vault.exists("src/app.py")
        assert not vault.exists("hack/evil.py")

    def test_no_access_allows_all(self, temp_db):
        vault = Vault(temp_db, "tester")

        snapshot = {}
        current = {"anywhere/file.txt": b"content"}

        _diff_and_commit(vault, snapshot, current, "", access=None)

        assert vault.read("anywhere/file.txt") == b"content"

    def test_commit_msg_used_and_not_committed(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("src/app.py", b"original")

        snapshot = {"src/app.py": b"original", "COMMIT_MSG": b""}
        current = {"src/app.py": b"modified", "COMMIT_MSG": b"Fixed the bug in app.py"}

        _diff_and_commit(vault, snapshot, current, "")

        assert vault.read("src/app.py") == b"modified"
        # COMMIT_MSG should not be in the vault
        assert not vault.exists("COMMIT_MSG")
        # Check that commit message was used
        commits = vault.commit_log()
        assert any("Fixed the bug in app.py" in c.message for c in commits)

    def test_deleted_ro_file_rejected(self, temp_db):
        vault = Vault(temp_db, "tester")
        vault.write("lib/util.py", b"original")

        snapshot = {"lib/util.py": b"original"}
        current = {}  # agent deleted it
        access = [("lib/**", "ro")]

        _diff_and_commit(vault, snapshot, current, "", access=access)

        # Deletion of ro file should be rejected
        assert vault.read("lib/util.py") == b"original"

    def test_added_file_in_rw_succeeds(self, temp_db):
        vault = Vault(temp_db, "tester")

        snapshot = {}
        current = {"src/new.py": b"new file"}
        access = [("src/**", "rw")]

        _diff_and_commit(vault, snapshot, current, "", access=access)

        assert vault.read("src/new.py") == b"new file"


# ── AGENTS.md injection ──────────────────────────────────────────────────────

class TestAgentsMdAccessSection:
    """_build_snapshot should include access policy in AGENTS.md when access rules are set."""

    def test_access_section_included(self, temp_db):
        with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
            fs = ctx.fs()

            access = [("src/**", "rw"), ("lib/**", "ro")]
            snapshot = _build_snapshot(fs, "", access=access)

            content = snapshot["AGENTS.md"].decode()
            assert "File Access Policy" in content
            assert "src/**" in content
            assert "lib/**" in content
            assert "COMMIT_MSG" in content
            assert "rejected" in content.lower() or "lost" in content.lower()

    def test_commit_msg_injected(self, temp_db):
        with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
            fs = ctx.fs()

            snapshot = _build_snapshot(fs, "", access=None)

            # COMMIT_MSG should always be injected
            assert "COMMIT_MSG" in snapshot

    def test_no_access_no_policy_section(self, temp_db):
        with SystemContext(user="test", fsimage=temp_db, interactive=False) as ctx:
            fs = ctx.fs()

            snapshot = _build_snapshot(fs, "", access=None)

            content = snapshot["AGENTS.md"].decode()
            assert "File Access Policy" not in content
