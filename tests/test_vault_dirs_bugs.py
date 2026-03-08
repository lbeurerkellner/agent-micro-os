"""Test cases exposing bugs in vault directory support."""

import pytest
from fs.vault import Vault


# ── Bug 1: move() leaves orphan directory markers behind ──


def test_move_directory_moves_dir_markers(temp_db):
    """move() of a directory should also move its directory markers."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("src/sub")  # explicit empty subdir
    vault.write("src/file.txt", b"content")

    vault.move("src", "dst")

    # Files should be moved
    assert vault.read("dst/file.txt") == b"content"
    assert "src/file.txt" not in vault.list()

    # Directory markers should also be moved
    assert vault.is_dir("dst"), "dst should be a directory after move"
    assert vault.is_dir("dst/sub"), "dst/sub should exist after move"
    assert not vault._has_dir_marker("src"), "src marker should be removed"
    assert not vault._has_dir_marker("src/sub"), "src/sub marker should be removed"


def test_move_directory_empty_subdirs_preserved(temp_db):
    """move() should preserve empty subdirectories (created with mkdir)."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("project/empty_dir")
    vault.write("project/readme.txt", b"hello")

    vault.move("project", "renamed")

    assert vault.is_dir("renamed/empty_dir"), "empty subdir should survive move"
    assert not vault.exists("project"), "old path should not exist"


# ── Bug 2: copy() loses empty subdirectories ──


def test_copy_directory_copies_dir_markers(temp_db):
    """copy() of a directory should also copy its directory markers."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("src/empty_sub")
    vault.write("src/file.txt", b"content")

    vault.copy("src", "dst")

    # Files should be copied
    assert vault.read("dst/file.txt") == b"content"
    assert vault.read("src/file.txt") == b"content"  # original still there

    # Directory markers should also be copied
    assert vault.is_dir("dst/empty_sub"), "empty subdir should be copied"


# ── Bug 3: delete() gives wrong error for empty explicit directory ──


def test_delete_empty_explicit_dir_error_message(temp_db):
    """delete() on an empty explicit dir should say 'is a directory'."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("empty")

    with pytest.raises(ValueError, match="is a directory"):
        vault.delete("empty")


# ── Bug 4: mkdir inside a commit is not transactional ──


def test_mkdir_inside_commit_is_transactional(temp_db):
    """mkdir called (indirectly) during a commit should roll back on conflict."""
    vault = Vault(temp_db, "user1")
    vault.write("file.txt", b"original")

    vault.begin_commit()
    # Write to a new nested path — this triggers _ensure_parents → mkdir
    vault.write("newdir/nested/file.txt", b"new content")
    # Write the file that will conflict (captures base hash now)
    vault.write("file.txt", b"commit change")

    # Simulate concurrent modification AFTER base hash was captured
    other = Vault(temp_db, "user1")
    other.write("file.txt", b"concurrent change")

    with pytest.raises(ValueError, match="Conflict"):
        vault.end_commit("should fail")

    # The directory markers created during the commit should NOT persist
    # since the commit was rolled back
    fresh = Vault(temp_db, "user1")
    assert not fresh._has_dir_marker("newdir"), (
        "dir marker should be rolled back with the commit"
    )
    assert not fresh._has_dir_marker("newdir/nested"), (
        "nested dir marker should be rolled back with the commit"
    )


# ── Bug 5: _ensure_parents during commit writes directly to DB ──


def test_ensure_parents_during_commit_not_leaked(temp_db):
    """Parent dirs auto-created during a commit should not persist if commit
    is abandoned (no end_commit called)."""
    vault = Vault(temp_db, "user1")
    vault.begin_commit()
    vault.write("deep/path/file.txt", b"data")

    # Abandon the commit without calling end_commit
    # (simulate crash / error path by resetting state)
    vault._current_commit_id = None
    vault._pending_writes.clear()

    # The dir markers were written directly to DB by _ensure_parents
    # even though the commit was never finalized
    fresh = Vault(temp_db, "user1")
    assert not fresh._has_dir_marker("deep"), (
        "dir marker should not exist for abandoned commit"
    )
    assert not fresh._has_dir_marker("deep/path"), (
        "nested dir marker should not exist for abandoned commit"
    )


# ── Bug 6: rmdir on virtual-only directory (no explicit marker) ──


def test_rmdir_virtual_dir_after_files_deleted(temp_db):
    """After deleting all files under a virtual directory, rmdir should work
    or at least give a sensible error."""
    vault = Vault(temp_db, "user1")
    vault.write("vdir/file.txt", b"content")
    vault.delete("vdir/file.txt")

    # "vdir" still exists as an explicit dir (auto-created by write)
    # rmdir should succeed on it since it's now empty
    vault.rmdir("vdir")
    assert not vault.exists("vdir")


# ── Bug 7: move() file into a path where a dir marker exists ──


def test_write_file_at_dir_marker_path(temp_db):
    """Writing a file at a path that has a directory marker should fail."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")

    with pytest.raises(ValueError, match="is a directory"):
        vault.write("docs", b"I am a file, not a dir")


# ── Bug 8: list_with_metadata prefix includes exact match incorrectly ──


def test_list_prefix_no_false_positives(temp_db):
    """list(prefix='do') should not match 'documents' — it should behave
    like a directory prefix, not a string prefix."""
    vault = Vault(temp_db, "user1")
    vault.write("do/file.txt", b"a")
    vault.write("documents/file.txt", b"b")

    # prefix="do" uses LIKE 'do%' which matches both "do/file.txt" AND "documents/file.txt"
    result = vault.list(prefix="do")
    assert "documents/file.txt" not in result, (
        "prefix='do' should not match 'documents/file.txt'"
    )


def test_list_with_metadata_prefix_no_false_positives(temp_db):
    """list_with_metadata(prefix='do') should not match 'documents'."""
    vault = Vault(temp_db, "user1")
    vault.write("do/file.txt", b"a")
    vault.write("documents/file.txt", b"b")

    result = vault.list_with_metadata(prefix="do")
    paths = [m.filepath for m in result]
    assert "documents/file.txt" not in paths, (
        "prefix='do' should not match 'documents/file.txt'"
    )
