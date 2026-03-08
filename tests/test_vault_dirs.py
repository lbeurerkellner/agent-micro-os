"""Test cases for vault directory (mkdir/rmdir) support."""

import pytest
from fs.vault import Vault


def test_mkdir_creates_directory(temp_db):
    """mkdir creates an explicit directory that persists when empty."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")
    assert vault.exists("docs")
    assert vault.is_dir("docs")


def test_mkdir_not_in_file_list(temp_db):
    """Directories created by mkdir don't appear in list()."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")
    assert "docs" not in vault.list()


def test_mkdir_creates_parents(temp_db):
    """mkdir auto-creates parent directories."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("a/b/c")
    assert vault.is_dir("a")
    assert vault.is_dir("a/b")
    assert vault.is_dir("a/b/c")


def test_mkdir_idempotent(temp_db):
    """mkdir on an existing directory is a no-op."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")
    vault.mkdir("docs")  # should not raise
    assert vault.is_dir("docs")


def test_mkdir_rejects_existing_file(temp_db):
    """mkdir fails if a file already exists at that path."""
    vault = Vault(temp_db, "user1")
    vault.write("docs", b"I am a file")
    with pytest.raises(ValueError, match="exists as a file"):
        vault.mkdir("docs")


def test_mkdir_strips_slashes(temp_db):
    """mkdir normalizes leading/trailing slashes."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("/docs/")
    assert vault.is_dir("docs")


def test_mkdir_empty_path_raises(temp_db):
    """mkdir with empty path raises ValueError."""
    vault = Vault(temp_db, "user1")
    with pytest.raises(ValueError):
        vault.mkdir("")


def test_rmdir_empty_directory(temp_db):
    """rmdir removes an empty explicit directory."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")
    vault.rmdir("docs")
    assert not vault.exists("docs")
    assert not vault.is_dir("docs")


def test_rmdir_nonempty_raises(temp_db):
    """rmdir fails if directory contains files."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")
    vault.write("docs/file.txt", b"content")
    with pytest.raises(ValueError, match="not empty"):
        vault.rmdir("docs")


def test_rmdir_nonempty_with_subdirs(temp_db):
    """rmdir fails if directory contains child directories."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("a/b")
    with pytest.raises(ValueError, match="not empty"):
        vault.rmdir("a")


def test_rmdir_nonexistent_raises(temp_db):
    """rmdir on a path that doesn't exist raises an error."""
    vault = Vault(temp_db, "user1")
    with pytest.raises(FileNotFoundError):
        vault.rmdir("ghost")


def test_rmdir_auto_created_dir_with_files_raises(temp_db):
    """rmdir on an auto-created directory that still has files raises ValueError."""
    vault = Vault(temp_db, "user1")
    vault.write("docs/file.txt", b"content")
    # "docs" was auto-created by write, but has files — can't rmdir
    with pytest.raises(ValueError, match="not empty"):
        vault.rmdir("docs")


def test_is_dir_explicit_and_virtual(temp_db):
    """is_dir returns True for both explicit and virtual directories."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("explicit")
    vault.write("virtual/file.txt", b"content")
    assert vault.is_dir("explicit")
    assert vault.is_dir("virtual")


def test_exists_explicit_dir(temp_db):
    """exists returns True for explicit empty directories."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("empty_dir")
    assert vault.exists("empty_dir")
    # But it's not a file
    assert vault.is_dir("empty_dir")


def test_mkdir_user_isolation(temp_db):
    """Directories are scoped to the user."""
    v1 = Vault(temp_db, "alice")
    v2 = Vault(temp_db, "bob")
    v1.mkdir("secret")
    assert v1.is_dir("secret")
    assert not v2.exists("secret")


def test_log_on_directory(temp_db):
    """log() on a directory returns its creation event."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")
    versions = vault.log("docs")
    assert len(versions) == 1
    assert versions[0].author == "user1"
    assert versions[0].hash == "directory"


def test_delete_nonempty_dir_raises(temp_db):
    """delete() on a non-empty directory raises an error."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")
    vault.write("docs/file.txt", b"content")
    with pytest.raises(ValueError, match="is a directory"):
        vault.delete("docs")


def test_write_does_not_overwrite_dir_marker(temp_db):
    """Writing a file under a directory doesn't remove the dir marker."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")
    vault.write("docs/file.txt", b"content")
    # Delete the file — directory should still exist
    vault.delete("docs/file.txt")
    assert vault.is_dir("docs")
    assert vault.exists("docs")


def test_write_auto_creates_parent_dirs(temp_db):
    """write() with parents=True (default) auto-creates parent directory markers."""
    vault = Vault(temp_db, "user1")
    vault.write("a/b/c.txt", b"content")
    assert vault.is_dir("a")
    assert vault.is_dir("a/b")
    assert vault._has_dir_marker("a")
    assert vault._has_dir_marker("a/b")


def test_write_parents_false_requires_parent(temp_db):
    """write() with parents=False raises when parent dir doesn't exist."""
    vault = Vault(temp_db, "user1")
    with pytest.raises(FileNotFoundError, match="No such file or directory"):
        vault.write("nonexistent/file.txt", b"content", parents=False)


def test_write_parents_false_succeeds_with_existing_dir(temp_db):
    """write() with parents=False works when parent dir exists."""
    vault = Vault(temp_db, "user1")
    vault.mkdir("docs")
    vault.write("docs/file.txt", b"content", parents=False)
    assert vault.read("docs/file.txt") == b"content"


def test_write_parents_false_succeeds_with_virtual_dir(temp_db):
    """write() with parents=False works when parent is a virtual directory."""
    vault = Vault(temp_db, "user1")
    vault.write("docs/existing.txt", b"existing")  # creates virtual dir + marker
    vault.write("docs/new.txt", b"new", parents=False)
    assert vault.read("docs/new.txt") == b"new"


def test_write_root_level_no_parents_needed(temp_db):
    """write() at root level works regardless of parents flag."""
    vault = Vault(temp_db, "user1")
    vault.write("file.txt", b"content", parents=False)
    assert vault.read("file.txt") == b"content"


def test_write_auto_created_dirs_persist_after_file_delete(temp_db):
    """Parent dirs auto-created by write() persist after file is deleted."""
    vault = Vault(temp_db, "user1")
    vault.write("a/b/c.txt", b"content")
    vault.delete("a/b/c.txt")
    assert vault.is_dir("a")
    assert vault.is_dir("a/b")
