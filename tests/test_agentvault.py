"""Basic tests for fs package."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass

import pytest

import fs


@dataclass
class FileVersion:
    """Metadata for a file version."""

    version_id: str
    author: str
    timestamp: str
    hash: str

@dataclass
class Commit:
    """Metadata for a commit."""

    commit_id: str
    author: str
    timestamp: str
    message: str

class Vault:
    def __init__(self, filename: str, user: str):
        """
        :param filename: The vault DB file to use (sqlite)
        :param user: The name of the user (each user has their own vault partition)
        """
        ...

    def write(self, filepath: str, content: bytes):
        """
        Create a file in the vault.

        :param filepath: The path of the file to create
        :param content: The content of the file as bytes
        """
        ...

    def list(self) -> list[str]:
        """
        List all files in the vault.

        :return: A list of file paths
        """
        ...

    def read(self, filepath: str) -> bytes:
        """
        Read a file from the vault.

        :param filepath: The path of the file to read
        :return: The content of the file as bytes
        """
        ...

    def delete(self, filepath: str):
        """
        Delete a file from the vault.

        Also deletes all versions of the file (garbage collection).

        :param filepath: The path of the file to delete
        """
        ...

    def log(self, filepath: str) -> list[FileVersion]:
        """
        Returns metadata for all file versions.

        :param filepath: The path of the file to get the log for
        :return: A list of FileVersion objects (version_id, author, timestamp, hash)
        """
        ...

    def restore(self, filepath: str, version_id: str):
        """
        Restore a file to a previous version.

        :param filepath: The path of the file to restore
        :param version_id: The UUID of the version to restore
        """
        ...

# Dependency injection: replace stubs with actual implementation
Vault = fs.Vault # noqa: F811
FileVersion = fs.FileVersion # noqa: F811
Commit = fs.Commit # noqa: F811
FileMeta = fs.FileMeta


@pytest.fixture
def temp_db():
    """Fixture that provides a temporary database file path.

    Usage:
        def test_example(temp_db):
            vault = Vault(temp_db, "username")
            # use vault...
    """
    # Create a temporary file for the database
    fd, db_path = tempfile.mkstemp(suffix=".db")
    # Close the file descriptor as SQLite will handle the file
    import os
    os.close(fd)

    yield db_path

    # Cleanup: remove the database file
    if os.path.exists(db_path):
        os.remove(db_path)


def test_writes(temp_db):
    vault = Vault(temp_db, "testuser")

    vault.write("docs/file1.txt", b"Hello, World!")

    files = vault.list()
    assert "docs/file1.txt" in files

    
def test_can_look_at_old_versions(temp_db):
    vault = Vault(temp_db, "testuser")

    vault.write("docs/file2.txt", b"Version 1")
    vault.write("docs/file2.txt", b"Version 2")
    vault.write("docs/file2.txt", b"Version 3")

    # ensure file content is latest version
    content = vault.read("docs/file2.txt")
    assert content == b"Version 3", "File content should be the latest version"

    log = vault.log("docs/file2.txt")
    assert len(log) == 3, "There should be three versions in the log"

    # verify log returns FileVersion objects with correct attributes
    assert isinstance(log[0], FileVersion), "Log should contain FileVersion objects"
    assert log[0].version_id, "FileVersion should have version_id"
    assert log[0].author, "FileVersion should have author"
    assert log[0].timestamp, "FileVersion should have timestamp"
    assert log[0].hash, "FileVersion should have hash"

    # restore to version 1 using version_id
    vault.restore("docs/file2.txt", log[0].version_id)

    content = vault.read("docs/file2.txt")
    assert content == b"Version 1", "File content should be restored to version 1"

    # length of log is 4 now, because the restore counts as a new version
    log = vault.log("docs/file2.txt")
    assert len(log) == 4, "There should be four versions in the log after restore"

    
def test_isolated_between_users(temp_db):
    vault_user1 = Vault(temp_db, "user1")
    vault_user2 = Vault(temp_db, "user2")

    vault_user1.write("shared/file.txt", b"User 1's content")
    vault_user2.write("shared/file.txt", b"User 2's content")

    content_user1 = vault_user1.read("shared/file.txt")
    content_user2 = vault_user2.read("shared/file.txt")

    assert content_user1 == b"User 1's content", "User 1 should see their own content"
    assert content_user2 == b"User 2's content", "User 2 should see their own content"

def test_file_not_found(temp_db):
    vault = Vault(temp_db, "testuser")

    try:
        vault.read("nonexistent/file.txt")
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass  # Expected

def test_delete(temp_db):
    vault = Vault(temp_db, "testuser")

    vault.write("to_delete/file.txt", b"Some content")
    files = vault.list()
    assert "to_delete/file.txt" in files, "File should exist before deletion"

    vault.delete("to_delete/file.txt")
    files = vault.list()
    assert "to_delete/file.txt" not in files, "File should be deleted"

def test_delete_all_versions(temp_db):
    vault = Vault(temp_db, "testuser")

    vault.write("to_delete_versions/file.txt", b"Version 1")
    vault.write("to_delete_versions/file.txt", b"Version 2")

    log = vault.log("to_delete_versions/file.txt")
    assert len(log) == 2, "There should be two versions before deletion"

    vault.delete("to_delete_versions/file.txt")

    try:
        vault.read("to_delete_versions/file.txt")
        assert False, "Expected FileNotFoundError after deletion"
    except FileNotFoundError:
        pass  # Expected

    try:
        vault.log("to_delete_versions/file.txt")
        assert False, "Expected FileNotFoundError for log after deletion"
    except FileNotFoundError:
        pass  # Expected

def test_list_sort_by_recent(temp_db):
    import time
    vault = Vault(temp_db, "sort_test_user")

    # Create files with delays to ensure different timestamps
    vault.write("recent/file1.txt", b"First file")
    time.sleep(0.01)  # Small delay to ensure different timestamps
    vault.write("recent/file2.txt", b"Second file")
    time.sleep(0.01)
    vault.write("recent/file3.txt", b"Third file")

    # Default list (no guaranteed order)
    files_default = vault.list()
    assert len(files_default) == 3, "Should have 3 files"

    # List sorted by most recent
    files_recent = vault.list(sort_by_recent=True)
    assert len(files_recent) == 3, "Should have 3 files when sorted"
    assert files_recent[0] == "recent/file3.txt", "Most recent file should be first"
    assert files_recent[1] == "recent/file2.txt", "Second most recent should be second"
    assert files_recent[2] == "recent/file1.txt", "Oldest file should be last"

    # Update an old file to make it most recent
    time.sleep(0.01)
    vault.write("recent/file1.txt", b"Updated content")

    files_recent_updated = vault.list(sort_by_recent=True)
    assert files_recent_updated[0] == "recent/file1.txt", "Updated file should now be first"


def test_basic_commit(temp_db):
    """Test creating a commit with multiple file changes."""
    vault = Vault(temp_db, "commit_user")

    # Create initial versions of files
    vault.write("project/file1.txt", b"Initial content 1")
    vault.write("project/file2.txt", b"Initial content 2")
    vault.write("project/file3.txt", b"Initial content 3")

    # Create a commit with multiple changes
    vault.begin_commit()
    vault.write("project/file1.txt", b"Updated content 1")
    vault.write("project/file2.txt", b"Updated content 2")
    vault.end_commit("Update file1 and file2")

    # Verify the files have the new content
    assert vault.read("project/file1.txt") == b"Updated content 1"
    assert vault.read("project/file2.txt") == b"Updated content 2"
    assert vault.read("project/file3.txt") == b"Initial content 3", "Unchanged file should remain the same"


def test_commit_log(temp_db):
    """Test listing commits."""
    vault = Vault(temp_db, "commit_log_user")

    # Create some commits
    vault.begin_commit()
    vault.write("docs/readme.txt", b"Version 1")
    vault.end_commit("Initial commit")

    vault.begin_commit()
    vault.write("docs/readme.txt", b"Version 2")
    vault.write("docs/api.txt", b"API docs")
    vault.end_commit("Add API docs and update readme")

    # Get commit log
    commits = vault.commit_log()
    assert len(commits) == 2, "Should have 2 commits"

    # Verify commit structure
    assert isinstance(commits[0], Commit), "Should return Commit objects"
    assert commits[0].commit_id, "Commit should have an ID"
    assert commits[0].author, "Commit should have an author"
    assert commits[0].timestamp, "Commit should have a timestamp"
    assert commits[0].message == "Initial commit", "First commit message should match"
    assert commits[1].message == "Add API docs and update readme", "Second commit message should match"


def test_revert_commit(temp_db):
    """Test reverting a commit."""
    vault = Vault(temp_db, "revert_user")

    # Create initial state
    vault.write("app/config.txt", b"Config v1")
    vault.write("app/main.txt", b"Main v1")

    # Make a commit that changes both files
    vault.begin_commit()
    vault.write("app/config.txt", b"Config v2")
    vault.write("app/main.txt", b"Main v2")
    vault.end_commit("Bad update")

    # Verify files are updated
    assert vault.read("app/config.txt") == b"Config v2"
    assert vault.read("app/main.txt") == b"Main v2"

    # Get the commit ID
    commits = vault.commit_log()
    bad_commit = commits[-1]  # Most recent commit

    # Revert the commit
    vault.revert_commit(bad_commit.commit_id)

    # Verify files are restored to previous versions
    assert vault.read("app/config.txt") == b"Config v1", "Config should be reverted"
    assert vault.read("app/main.txt") == b"Main v1", "Main should be reverted"


def test_revert_commit_with_new_file(temp_db):
    """Test reverting a commit that created a new file."""
    vault = Vault(temp_db, "revert_new_file_user")

    # Create a commit with a new file
    vault.begin_commit()
    vault.write("new/feature.txt", b"New feature")
    vault.end_commit("Add new feature")

    # Verify file exists
    assert vault.read("new/feature.txt") == b"New feature"
    assert "new/feature.txt" in vault.list()

    # Revert the commit
    commits = vault.commit_log()
    vault.revert_commit(commits[0].commit_id)

    # The file should no longer exist (revert to "no file" state)
    try:
        vault.read("new/feature.txt")
        assert False, "File should not exist after reverting creation commit"
    except FileNotFoundError:
        pass  # Expected

    assert "new/feature.txt" not in vault.list(), "File should not be in list"


def test_writes_outside_commits(temp_db):
    """Test that writes outside commits still work."""
    vault = Vault(temp_db, "outside_commit_user")

    # Write outside commit
    vault.write("loose/file1.txt", b"Content 1")

    # Write inside commit
    vault.begin_commit()
    vault.write("loose/file2.txt", b"Content 2")
    vault.end_commit("Add file2")

    # Write outside commit again
    vault.write("loose/file3.txt", b"Content 3")

    # All files should exist
    assert vault.read("loose/file1.txt") == b"Content 1"
    assert vault.read("loose/file2.txt") == b"Content 2"
    assert vault.read("loose/file3.txt") == b"Content 3"

    # Only file2 should have a commit
    commits = vault.commit_log()
    assert len(commits) == 1, "Should have only 1 commit"
    assert commits[0].message == "Add file2"


def test_commit_selective_revert(temp_db):
    """Test that reverting a commit only undoes that commit's changes (Git-like behavior)."""
    vault = Vault(temp_db, "selective_revert_user")

    # Initial state: lines 1-3
    initial = b"Line 1\nLine 2\nLine 3\n"
    vault.write("doc/file.txt", initial)

    # Commit adds lines 4-5
    vault.begin_commit()
    with_additions = b"Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n"
    vault.write("doc/file.txt", with_additions)
    vault.end_commit("Add lines 4-5")

    # Later change: append line 6 (independent of commit)
    final = b"Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\n"
    vault.write("doc/file.txt", final)

    # Revert the commit should remove lines 4-5 but keep line 6
    commits = vault.commit_log()
    vault.revert_commit(commits[0].commit_id)

    # Result should be: Line 1-3 + Line 6 (commit's changes removed, later changes kept)
    expected = b"Line 1\nLine 2\nLine 3\nLine 6\n"
    assert vault.read("doc/file.txt") == expected, "Should remove commit's changes but keep later changes"


def test_commit_revert_with_modification(temp_db):
    """Test reverting a commit that modified existing lines."""
    vault = Vault(temp_db, "revert_modify_user")

    # Initial state
    vault.write("config/settings.txt", b"setting1=old\nsetting2=value\n")

    # Commit modifies setting1
    vault.begin_commit()
    vault.write("config/settings.txt", b"setting1=new\nsetting2=value\n")
    vault.end_commit("Update setting1")

    # Later change: add setting3 (independent)
    vault.write("config/settings.txt", b"setting1=new\nsetting2=value\nsetting3=added\n")

    # Revert should restore setting1=old but keep setting3=added
    commits = vault.commit_log()
    vault.revert_commit(commits[0].commit_id)

    expected = b"setting1=old\nsetting2=value\nsetting3=added\n"
    assert vault.read("config/settings.txt") == expected, "Should revert modification but keep later additions"


def test_commit_revert_with_multiple_independent_changes(temp_db):
    """Test reverting a commit when multiple lines were independently changed later."""
    vault = Vault(temp_db, "multi_change_user")

    # Initial state
    vault.write("config/settings.txt", b"setting1=old\nsetting2=value\n")

    # Commit modifies only setting1
    vault.begin_commit()
    vault.write("config/settings.txt", b"setting1=new\nsetting2=value\n")
    vault.end_commit("Update setting1")

    # Later changes: modify setting2 AND add setting3 (both independent of commit)
    vault.write("config/settings.txt", b"setting1=new\nsetting2=value_later\nsetting3=added\n")

    # Revert should restore setting1=old but keep both later changes
    commits = vault.commit_log()
    vault.revert_commit(commits[0].commit_id)

    expected = b"setting1=old\nsetting2=value_later\nsetting3=added\n"
    result = vault.read("config/settings.txt")
    assert result == expected, f"Should revert only commit's changes. Expected:\n{expected.decode()}\nGot:\n{result.decode()}"


def test_commit_revert_conflict(temp_db):
    """Test that reverting a commit raises an error when there are conflicts."""
    vault = Vault(temp_db, "conflict_user")

    # Initial state
    vault.write("code/main.py", b"def foo():\n    return 1\n")

    # Commit changes the return value
    vault.begin_commit()
    vault.write("code/main.py", b"def foo():\n    return 2\n")
    vault.end_commit("Change return value to 2")

    # Later change: modify the same line to a different value (conflict!)
    vault.write("code/main.py", b"def foo():\n    return 3\n")

    # Reverting should detect conflict (commit changed return 1->2, current is 3)
    commits = vault.commit_log()

    try:
        vault.revert_commit(commits[0].commit_id)
        assert False, "Should raise an error for conflicting changes"
    except ValueError as e:
        assert "conflict" in str(e).lower(), "Error should mention conflict"


def test_commit_revert_sequential_conflict(temp_db):
    """Test reverting an earlier commit when a later commit modified the same lines."""
    vault = Vault(temp_db, "sequential_conflict_user")

    # Initial state
    vault.write("config.txt", b"setting1=old\nsetting2=value\n")

    # Commit 2: changes setting2 to value2
    vault.begin_commit()
    vault.write("config.txt", b"setting1=old\nsetting2=value2\n")
    vault.end_commit("Change to value2")

    # Commit 3: changes setting2 again to value3
    vault.begin_commit()
    vault.write("config.txt", b"setting1=old\nsetting2=value3\n")
    vault.end_commit("Change to value3")

    # Try to revert commit 2 (should conflict because commit 3 also changed setting2)
    commits = vault.commit_log()
    commit2_id = commits[0].commit_id  # First commit

    try:
        vault.revert_commit(commit2_id)
        assert False, "Should raise an error when reverting a commit whose changes were modified by a later commit"
    except ValueError as e:
        assert "conflict" in str(e).lower(), "Error should mention conflict"


# ========== TRICKY EDGE CASE TESTS ==========

def test_empty_file_content(temp_db):
    """Test writing and reading empty files."""
    vault = Vault(temp_db, "empty_user")

    # Write empty file
    vault.write("empty/file.txt", b"")

    # Should be able to read it back
    content = vault.read("empty/file.txt")
    assert content == b"", "Empty file should return empty bytes"

    # Should appear in list
    assert "empty/file.txt" in vault.list()

    # Should have version history
    log = vault.log("empty/file.txt")
    assert len(log) == 1, "Empty file should still have version history"


def test_nested_begin_commit(temp_db):
    """Test calling begin_commit twice without end_commit."""
    vault = Vault(temp_db, "nested_user")

    vault.begin_commit()

    # Calling begin_commit again should raise an error
    try:
        vault.begin_commit()
        assert False, "Should raise an error when calling begin_commit twice"
    except (RuntimeError, ValueError):
        pass  # Expected - either error type is acceptable


def test_end_commit_without_begin(temp_db):
    """Test calling end_commit without begin_commit."""
    vault = Vault(temp_db, "orphan_end_user")

    try:
        vault.end_commit("Orphan commit")
        assert False, "Should raise an error when calling end_commit without begin_commit"
    except (RuntimeError, ValueError):
        pass  # Expected - either error type is acceptable


def test_revert_nonexistent_commit(temp_db):
    """Test reverting a commit ID that doesn't exist."""
    vault = Vault(temp_db, "fake_commit_user")

    vault.write("file.txt", b"Content")

    # Try to revert a fake UUID
    try:
        vault.revert_commit("00000000-0000-0000-0000-000000000000")
        assert False, "Should raise an error when reverting non-existent commit"
    except (ValueError, KeyError, FileNotFoundError) as e:
        pass  # Expected - any of these errors would be reasonable


def test_revert_after_file_deleted(temp_db):
    """Test reverting a commit on a file that was later deleted."""
    vault = Vault(temp_db, "deleted_file_user")

    # Create and commit a change
    vault.write("temp/file.txt", b"Version 1")
    vault.begin_commit()
    vault.write("temp/file.txt", b"Version 2")
    vault.end_commit("Update to v2")

    # Delete the file
    vault.delete("temp/file.txt")

    # Try to revert the commit - the file is gone!
    commits = vault.commit_log()

    # Should this recreate the file or error? Let's test it errors
    try:
        vault.revert_commit(commits[0].commit_id)
        # If it doesn't error, the file should be recreated
        content = vault.read("temp/file.txt")
        assert content == b"Version 1", "Reverting should recreate deleted file with previous content"
    except (FileNotFoundError, ValueError):
        pass  # Also acceptable to raise an error


def test_empty_filepath(temp_db):
    """Test using empty string as filepath."""
    vault = Vault(temp_db, "empty_path_user")

    try:
        vault.write("", b"Content")
        assert False, "Should raise an error for empty filepath"
    except ValueError:
        pass  # Expected


def test_commit_with_no_changes(temp_db):
    """Test creating a commit without any file changes."""
    vault = Vault(temp_db, "empty_commit_user")

    vault.write("file.txt", b"Content")

    # Begin and end commit without any writes
    vault.begin_commit()

    try:
        vault.end_commit("Empty commit")
        assert False, "Should raise an error for empty commit"
    except ValueError:
        pass  # Expected

    # Should not create a commit
    commits = vault.commit_log()
    assert len(commits) == 0, "Empty commits should not be created"


def test_write_same_file_twice_in_commit(temp_db):
    """Test writing the same file multiple times within one commit."""
    vault = Vault(temp_db, "double_write_user")

    vault.write("file.txt", b"Initial")

    vault.begin_commit()
    vault.write("file.txt", b"First write in commit")
    vault.write("file.txt", b"Second write in commit")
    vault.end_commit("Double write")

    # Should keep the last write
    content = vault.read("file.txt")
    assert content == b"Second write in commit", "Should keep the last write in commit"

    # Should only create ONE version for the commit (last write wins)
    log = vault.log("file.txt")
    assert len(log) == 2, "Only the last write in a commit should create a version"


def test_restore_to_nonexistent_version(temp_db):
    """Test restoring to a version ID that doesn't exist."""
    vault = Vault(temp_db, "bad_version_user")

    vault.write("file.txt", b"Content")

    # Try to restore to fake version
    try:
        vault.restore("file.txt", "00000000-0000-0000-0000-000000000000")
        assert False, "Should raise an error when restoring to non-existent version"
    except (ValueError, KeyError, FileNotFoundError):
        pass  # Expected


def test_delete_during_commit(temp_db):
    """Test deleting a file during a commit."""
    vault = Vault(temp_db, "delete_commit_user")

    vault.write("file1.txt", b"File 1")
    vault.write("file2.txt", b"File 2")

    vault.begin_commit()
    vault.write("file1.txt", b"Updated File 1")
    vault.delete("file2.txt")
    vault.end_commit("Update file1 and delete file2")

    # file1 should be updated, file2 should be deleted
    assert vault.read("file1.txt") == b"Updated File 1"
    assert "file2.txt" not in vault.list()

    # Reverting should restore file2 and revert file1
    commits = vault.commit_log()
    vault.revert_commit(commits[0].commit_id)

    assert vault.read("file1.txt") == b"File 1", "file1 should be reverted"
    assert vault.read("file2.txt") == b"File 2", "file2 should be restored"


def test_path_normalization(temp_db):
    """Test that different path representations are handled correctly."""
    vault = Vault(temp_db, "path_norm_user")

    # Write with one path
    vault.write("docs/file.txt", b"Content")

    # Try to read with different path representations
    # These should either all work or all fail consistently
    content1 = vault.read("docs/file.txt")
    assert content1 == b"Content"

    # Paths with leading/trailing slashes or dots might be normalized
    try:
        content2 = vault.read("./docs/file.txt")
        assert content2 == b"Content", "Should normalize ./ prefix"
    except FileNotFoundError:
        # Also acceptable - strict path matching
        pass


def test_restore_creates_new_version_with_same_content(temp_db):
    """Test that restoring to the same content still creates a new version."""
    vault = Vault(temp_db, "restore_dupe_user")

    vault.write("file.txt", b"Content")
    log = vault.log("file.txt")

    # Restore to the same version we already have
    vault.restore("file.txt", log[0].version_id)

    # Should create a new version even though content is identical
    log_after = vault.log("file.txt")
    assert len(log_after) == 2, "Restore should create new version even if content is identical"

    # Content should be the same
    assert vault.read("file.txt") == b"Content"


def test_binary_data_with_null_bytes(temp_db):
    """Test handling of binary data with null bytes."""
    vault = Vault(temp_db, "binary_user")

    # Binary data with null bytes
    binary_content = b"\x00\x01\x02\xff\xfe\x00\x00\x42"

    vault.write("binary/file.bin", binary_content)
    content = vault.read("binary/file.bin")

    assert content == binary_content, "Should handle binary data with null bytes correctly"


def test_very_long_filepath(temp_db):
    """Test handling of very long file paths."""
    vault = Vault(temp_db, "long_path_user")

    # Create a very long path
    long_path = "a/" * 100 + "file.txt"  # 202 characters

    vault.write(long_path, b"Content")
    content = vault.read(long_path)
    assert content == b"Content"
    assert long_path in vault.list()


def test_unicode_in_filepath(temp_db):
    """Test handling of unicode characters in file paths."""
    vault = Vault(temp_db, "unicode_user")

    # Unicode path with emojis and special characters
    unicode_path = "docs/文档/файл-🎉.txt"

    vault.write(unicode_path, b"Unicode content")
    content = vault.read(unicode_path)
    assert content == b"Unicode content"
    assert unicode_path in vault.list()


def test_commit_log_ordering(temp_db):
    """Test that commit log returns commits in correct order."""
    vault = Vault(temp_db, "commit_order_user")

    vault.begin_commit()
    vault.write("file.txt", b"V1")
    vault.end_commit("First commit")

    vault.begin_commit()
    vault.write("file.txt", b"V2")
    vault.end_commit("Second commit")

    vault.begin_commit()
    vault.write("file.txt", b"V3")
    vault.end_commit("Third commit")

    commits = vault.commit_log()
    assert len(commits) == 3

    # Should be in chronological order (oldest first) or reverse?
    # Let's assert chronological (oldest first) based on existing test pattern
    assert commits[0].message == "First commit"
    assert commits[1].message == "Second commit"
    assert commits[2].message == "Third commit"


def test_revert_twice_same_commit(temp_db):
    """Test reverting the same commit twice."""
    vault = Vault(temp_db, "double_revert_user")

    vault.write("file.txt", b"V1")

    vault.begin_commit()
    vault.write("file.txt", b"V2")
    vault.end_commit("Change to V2")

    commits = vault.commit_log()
    commit_id = commits[0].commit_id

    # First revert
    vault.revert_commit(commit_id)
    assert vault.read("file.txt") == b"V1"

    # Second revert of same commit - should this re-apply V2 or error?
    # Git-like behavior: reverting a revert re-applies the changes
    # But that would require tracking revert commits... Let's test it errors
    try:
        vault.revert_commit(commit_id)
        # If it works, it should re-apply V2
        content = vault.read("file.txt")
        assert content == b"V2", "Reverting a revert should re-apply changes"
    except ValueError:
        # Also reasonable to throw an error
        pass


def test_multiple_users_same_filename_commit_isolation(temp_db):
    """Test that commits are isolated between users."""
    vault1 = Vault(temp_db, "user1")
    vault2 = Vault(temp_db, "user2")

    # Both users create commits on same filename
    vault1.begin_commit()
    vault1.write("shared.txt", b"User1 content")
    vault1.end_commit("User1 commit")

    vault2.begin_commit()
    vault2.write("shared.txt", b"User2 content")
    vault2.end_commit("User2 commit")

    # Each user should only see their own commits
    commits1 = vault1.commit_log()
    commits2 = vault2.commit_log()

    assert len(commits1) == 1, "User1 should only see their commit"
    assert len(commits2) == 1, "User2 should only see their commit"
    assert commits1[0].message == "User1 commit"
    assert commits2[0].message == "User2 commit"

    # User1 shouldn't be able to revert User2's commit
    try:
        vault1.revert_commit(commits2[0].commit_id)
        assert False, "User should not be able to revert another user's commit"
    except (ValueError, KeyError, FileNotFoundError):
        pass  # Expected


def test_read_your_own_writes_during_commit(temp_db):
    """Test that you can read your own uncommitted writes during a commit."""
    vault = Vault(temp_db, "test_user")

    # Write initial version outside commit
    vault.write("file.txt", b"Version 1")

    # Start commit and write new version
    vault.begin_commit()
    vault.write("file.txt", b"Version 2 (uncommitted)")

    # Should be able to read the uncommitted write
    content = vault.read("file.txt")
    assert content == b"Version 2 (uncommitted)", "Should read uncommitted write during commit"

    # Write a new file in the commit
    vault.write("newfile.txt", b"New content")

    # Should be able to read the new uncommitted file
    new_content = vault.read("newfile.txt")
    assert new_content == b"New content", "Should read new uncommitted file"

    # Should see new file in list
    files = vault.list()
    assert "file.txt" in files
    assert "newfile.txt" in files

    # End commit
    vault.end_commit("Test commit")

    # After commit, should still be able to read
    content_after = vault.read("file.txt")
    assert content_after == b"Version 2 (uncommitted)"


def test_read_your_own_deletes_during_commit(temp_db):
    """Test that deleted files are not visible during a commit."""
    vault = Vault(temp_db, "test_user")

    # Create a file
    vault.write("to_delete.txt", b"Will be deleted")
    vault.write("to_keep.txt", b"Will be kept")

    # Start commit and delete file
    vault.begin_commit()
    vault.delete("to_delete.txt")

    # Deleted file should not be visible
    try:
        vault.read("to_delete.txt")
        assert False, "Should not be able to read deleted file during commit"
    except FileNotFoundError:
        pass  # Expected

    # Should not appear in list
    files = vault.list()
    assert "to_delete.txt" not in files, "Deleted file should not appear in list"
    assert "to_keep.txt" in files, "Other files should still appear"

    # End commit
    vault.end_commit("Delete file")

    # After commit, file should still be gone
    try:
        vault.read("to_delete.txt")
        assert False, "Should not be able to read deleted file after commit"
    except FileNotFoundError:
        pass  # Expected


# ========== CONFLICT DETECTION TESTS ==========

def test_concurrent_write_conflict(temp_db):
    """Test that concurrent writes to the same file are detected."""
    vault1 = Vault(temp_db, "conflict_user")
    vault2 = Vault(temp_db, "conflict_user")

    # Create initial file
    vault1.write("file.txt", b"Initial content")

    # Both vaults start commits
    vault1.begin_commit()
    vault2.begin_commit()

    # Both modify the same file
    vault1.write("file.txt", b"Vault1 changes")
    vault2.write("file.txt", b"Vault2 changes")

    # First commit succeeds
    vault1.end_commit("Vault1 commit")

    # Second commit should fail with conflict
    try:
        vault2.end_commit("Vault2 commit")
        assert False, "Should raise conflict error"
    except ValueError as e:
        assert "conflict" in str(e).lower(), f"Error should mention conflict: {e}"


def test_concurrent_delete_conflict(temp_db):
    """Test that concurrent delete conflicts are detected."""
    vault1 = Vault(temp_db, "conflict_user")
    vault2 = Vault(temp_db, "conflict_user")

    # Create initial file
    vault1.write("file.txt", b"Content")

    # Both vaults start commits
    vault1.begin_commit()
    vault2.begin_commit()

    # Vault1 modifies, Vault2 deletes
    vault1.write("file.txt", b"Modified")
    vault2.delete("file.txt")

    # First commit succeeds
    vault1.end_commit("Modify file")

    # Second commit should fail with conflict
    try:
        vault2.end_commit("Delete file")
        assert False, "Should raise conflict error"
    except ValueError as e:
        assert "conflict" in str(e).lower()


def test_no_conflict_different_files(temp_db):
    """Test that modifying different files doesn't cause conflicts."""
    vault1 = Vault(temp_db, "no_conflict_user")
    vault2 = Vault(temp_db, "no_conflict_user")

    # Create initial files
    vault1.write("file1.txt", b"File 1")
    vault1.write("file2.txt", b"File 2")

    # Both vaults start commits
    vault1.begin_commit()
    vault2.begin_commit()

    # Modify different files
    vault1.write("file1.txt", b"Modified by vault1")
    vault2.write("file2.txt", b"Modified by vault2")

    # Both commits should succeed
    vault1.end_commit("Modify file1")
    vault2.end_commit("Modify file2")

    # Verify both changes were applied
    vault3 = Vault(temp_db, "no_conflict_user")
    assert vault3.read("file1.txt") == b"Modified by vault1"
    assert vault3.read("file2.txt") == b"Modified by vault2"


def test_multiple_writes_same_file_in_commit_no_conflict(temp_db):
    """Test that multiple writes to same file in one commit don't cause self-conflict."""
    vault1 = Vault(temp_db, "multi_write_user")
    vault2 = Vault(temp_db, "multi_write_user")

    # Create initial file
    vault1.write("file.txt", b"Initial")

    # Vault1 starts commit and writes multiple times
    vault1.begin_commit()
    vault1.write("file.txt", b"First write")
    vault1.write("file.txt", b"Second write")
    vault1.write("file.txt", b"Third write")

    # Vault2 also modifies
    vault2.begin_commit()
    vault2.write("file.txt", b"Concurrent change")

    # Vault1's commit should succeed (multiple writes to same file OK)
    vault1.end_commit("Multiple writes")

    # Vault2's commit should fail (conflict with vault1)
    try:
        vault2.end_commit("Concurrent")
        assert False, "Should raise conflict error"
    except ValueError as e:
        assert "conflict" in str(e).lower()


def test_conflict_on_new_file_creation(temp_db):
    """Test conflict when two vaults try to create the same new file."""
    vault1 = Vault(temp_db, "new_file_user")
    vault2 = Vault(temp_db, "new_file_user")

    # Both vaults start commits
    vault1.begin_commit()
    vault2.begin_commit()

    # Both create the same new file
    vault1.write("newfile.txt", b"Created by vault1")
    vault2.write("newfile.txt", b"Created by vault2")

    # First commit succeeds
    vault1.end_commit("Create newfile")

    # Second commit should fail with conflict
    try:
        vault2.end_commit("Also create newfile")
        assert False, "Should raise conflict error for concurrent file creation"
    except ValueError as e:
        assert "conflict" in str(e).lower()


def test_no_conflict_after_successful_commit(temp_db):
    """Test that commits based on latest version don't conflict."""
    vault1 = Vault(temp_db, "sequential_user")

    # Create initial file
    vault1.write("file.txt", b"Version 1")

    # First commit
    vault1.begin_commit()
    vault1.write("file.txt", b"Version 2")
    vault1.end_commit("Update to v2")

    # Second commit (based on latest version) should succeed
    vault1.begin_commit()
    vault1.write("file.txt", b"Version 3")
    vault1.end_commit("Update to v3")

    assert vault1.read("file.txt") == b"Version 3"


def test_conflict_clears_pending_changes(temp_db):
    """Test that conflict detection clears pending changes on error."""
    vault1 = Vault(temp_db, "clear_test_user")
    vault2 = Vault(temp_db, "clear_test_user")

    # Create initial file
    vault1.write("file.txt", b"Initial")

    # Both start commits
    vault1.begin_commit()
    vault2.begin_commit()

    # Both modify
    vault1.write("file.txt", b"Change 1")
    vault2.write("file.txt", b"Change 2")

    # First succeeds
    vault1.end_commit("Commit 1")

    # Second fails
    try:
        vault2.end_commit("Commit 2")
        assert False, "Should fail"
    except ValueError:
        pass

    # Vault2 should be able to start a new commit
    vault2.begin_commit()
    vault2.write("file.txt", b"Retry change")
    vault2.end_commit("Retry commit")

    assert vault2.read("file.txt") == b"Retry change"


# ========== LIST WITH METADATA TESTS ==========


def test_list_with_metadata_basic(temp_db):
    """Test that list_with_metadata returns FileMeta objects with correct fields."""
    vault = Vault(temp_db, "meta_user")

    vault.write("docs/file1.txt", b"Hello, World!")
    vault.write("docs/file2.txt", b"Short")

    metas = vault.list_with_metadata()

    assert len(metas) == 2, "Should return metadata for both files"

    # Build a lookup by filepath
    by_path = {m.filepath: m for m in metas}

    assert "docs/file1.txt" in by_path
    assert "docs/file2.txt" in by_path

    m1 = by_path["docs/file1.txt"]
    assert isinstance(m1, FileMeta), "Should return FileMeta objects"
    assert m1.filepath == "docs/file1.txt"
    assert m1.timestamp is not None, "Vault files should have a timestamp"
    assert m1.author == "meta_user", "Author should default to vault user"
    assert m1.size == len(b"Hello, World!"), "Size should match content length"

    m2 = by_path["docs/file2.txt"]
    assert m2.size == len(b"Short")


def test_list_with_metadata_sort_by_recent(temp_db):
    """Test that sort_by_recent orders by most recently updated first."""
    import time
    vault = Vault(temp_db, "meta_sort_user")

    vault.write("file1.txt", b"First")
    time.sleep(0.01)
    vault.write("file2.txt", b"Second")
    time.sleep(0.01)
    vault.write("file3.txt", b"Third")

    metas = vault.list_with_metadata(sort_by_recent=True)
    paths = [m.filepath for m in metas]

    assert paths[0] == "file3.txt", "Most recent file should be first"
    assert paths[1] == "file2.txt"
    assert paths[2] == "file1.txt", "Oldest file should be last"

    # Update oldest file to make it most recent
    time.sleep(0.01)
    vault.write("file1.txt", b"Updated")

    metas = vault.list_with_metadata(sort_by_recent=True)
    assert metas[0].filepath == "file1.txt", "Updated file should now be first"
    assert metas[0].size == len(b"Updated"), "Size should reflect latest content"


def test_list_with_metadata_after_update(temp_db):
    """Test that metadata reflects the latest version after updates."""
    import time
    vault = Vault(temp_db, "meta_update_user")

    vault.write("file.txt", b"V1")
    metas1 = vault.list_with_metadata()
    assert len(metas1) == 1
    ts1 = metas1[0].timestamp
    size1 = metas1[0].size

    time.sleep(0.01)
    vault.write("file.txt", b"Version 2 is longer")
    metas2 = vault.list_with_metadata()
    assert len(metas2) == 1
    ts2 = metas2[0].timestamp
    size2 = metas2[0].size

    assert ts2 >= ts1, "Timestamp should not decrease after update"
    assert size2 == len(b"Version 2 is longer")
    assert size2 != size1, "Size should change after content update"


def test_list_with_metadata_excludes_deleted(temp_db):
    """Test that deleted files don't appear in metadata listing."""
    vault = Vault(temp_db, "meta_del_user")

    vault.write("keep.txt", b"Keep me")
    vault.write("delete.txt", b"Delete me")
    vault.delete("delete.txt")

    metas = vault.list_with_metadata()
    paths = [m.filepath for m in metas]

    assert "keep.txt" in paths
    assert "delete.txt" not in paths, "Deleted files should not appear"


def test_list_with_metadata_during_commit(temp_db):
    """Test that pending writes appear during a commit (read-your-own-writes)."""
    vault = Vault(temp_db, "meta_commit_user")

    vault.write("existing.txt", b"Existing content")

    vault.begin_commit()
    vault.write("new_in_commit.txt", b"New file")
    vault.write("existing.txt", b"Updated in commit")

    metas = vault.list_with_metadata()
    paths = [m.filepath for m in metas]

    assert "existing.txt" in paths, "Existing file should appear"
    assert "new_in_commit.txt" in paths, "Pending new file should appear"

    vault.end_commit("Test commit")


def test_list_with_metadata_during_commit_excludes_pending_deletes(temp_db):
    """Test that pending deletes are excluded during a commit."""
    vault = Vault(temp_db, "meta_commit_del_user")

    vault.write("file1.txt", b"File 1")
    vault.write("file2.txt", b"File 2")

    vault.begin_commit()
    vault.delete("file2.txt")

    metas = vault.list_with_metadata()
    paths = [m.filepath for m in metas]

    assert "file1.txt" in paths
    assert "file2.txt" not in paths, "Pending deleted file should not appear"

    vault.end_commit("Delete file2")


# ========== APPEND MODE TESTS ==========


def test_append_mode_updates_in_place(temp_db):
    """Test that mode='a' appends content to existing version in-place."""
    vault = Vault(temp_db, "append_user")

    vault.write("log.txt", b"Line 1\n", mode="a")
    log1 = vault.log("log.txt")
    assert len(log1) == 1

    # Append more content (just the new chunk)
    vault.write("log.txt", b"Line 2\n", mode="a")

    # Should still be one version (updated in place)
    log2 = vault.log("log.txt")
    assert len(log2) == 1, "Append should update in place, not create a new version"

    # Content should be the concatenation
    assert vault.read("log.txt") == b"Line 1\nLine 2\n"

    # Append again
    vault.write("log.txt", b"Line 3\n", mode="a")
    log3 = vault.log("log.txt")
    assert len(log3) == 1, "Multiple appends should still be one version"
    assert vault.read("log.txt") == b"Line 1\nLine 2\nLine 3\n"


def test_append_mode_new_file(temp_db):
    """Test that mode='a' creates the file if it doesn't exist."""
    vault = Vault(temp_db, "append_new_user")

    vault.write("new.txt", b"First content", mode="a")
    assert vault.read("new.txt") == b"First content"

    log = vault.log("new.txt")
    assert len(log) == 1


def test_append_mode_in_commit(temp_db):
    """Test that mode='a' inside a commit creates exactly one version (revertible)."""
    vault = Vault(temp_db, "append_commit_user")

    vault.write("log.txt", b"Initial")

    vault.begin_commit()
    vault.write("log.txt", b"Initial\nMore", mode="a")
    vault.write("log.txt", b"Initial\nMore\nEven more", mode="a")
    vault.end_commit("Append log")

    # Should have: initial version + one commit version = 2
    log = vault.log("log.txt")
    assert len(log) == 2, "Commit should create exactly one new version"
    assert vault.read("log.txt") == b"Initial\nMore\nEven more"

    # Should be revertible
    commits = vault.commit_log()
    vault.revert_commit(commits[0].commit_id)
    assert vault.read("log.txt") == b"Initial"


def test_default_mode_unchanged(temp_db):
    """Test that default write (no mode) still creates new versions even for extensions."""
    vault = Vault(temp_db, "default_mode_user")

    vault.write("file.txt", b"V1")
    vault.write("file.txt", b"V1 extended")  # Extension, but no mode="a"

    log = vault.log("file.txt")
    assert len(log) == 2, "Default write should always create a new version"


# ========== COPY TESTS ==========


def test_copy_file(temp_db):
    """Test copying a file to a new path."""
    vault = Vault(temp_db, "cp_user")

    vault.write("src/file.txt", b"Hello, World!")

    vault.copy("src/file.txt", "dst/file.txt")

    # Both files should exist with same content
    assert vault.read("src/file.txt") == b"Hello, World!", "Source should still exist"
    assert vault.read("dst/file.txt") == b"Hello, World!", "Destination should have same content"

    # Both should appear in list
    files = vault.list()
    assert "src/file.txt" in files
    assert "dst/file.txt" in files


def test_copy_file_overwrites_destination(temp_db):
    """Test that copying overwrites existing destination file."""
    vault = Vault(temp_db, "cp_overwrite_user")

    vault.write("src.txt", b"New content")
    vault.write("dst.txt", b"Old content")

    vault.copy("src.txt", "dst.txt")

    assert vault.read("dst.txt") == b"New content", "Destination should be overwritten"
    assert vault.read("src.txt") == b"New content", "Source should be unchanged"


def test_copy_nonexistent_source(temp_db):
    """Test that copying a nonexistent file raises FileNotFoundError."""
    vault = Vault(temp_db, "cp_noent_user")

    try:
        vault.copy("nonexistent.txt", "dst.txt")
        assert False, "Should raise FileNotFoundError"
    except FileNotFoundError:
        pass  # Expected


def test_copy_creates_new_version(temp_db):
    """Test that copy creates an independent version for the destination."""
    vault = Vault(temp_db, "cp_version_user")

    vault.write("original.txt", b"Content")
    vault.copy("original.txt", "copied.txt")

    # Destination should have its own version history
    log = vault.log("copied.txt")
    assert len(log) == 1, "Copied file should have its own version"

    # Modifying the copy should not affect the original
    vault.write("copied.txt", b"Modified copy")
    assert vault.read("original.txt") == b"Content", "Original should be unchanged"


def test_copy_directory_recursive(temp_db):
    """Test copying a directory recursively."""
    vault = Vault(temp_db, "cp_dir_user")

    vault.write("project/src/main.py", b"main code")
    vault.write("project/src/utils.py", b"utils code")
    vault.write("project/README.md", b"readme")

    vault.copy("project", "backup")

    # All files should be copied
    assert vault.read("backup/src/main.py") == b"main code"
    assert vault.read("backup/src/utils.py") == b"utils code"
    assert vault.read("backup/README.md") == b"readme"

    # Originals should still exist
    assert vault.read("project/src/main.py") == b"main code"
    assert vault.read("project/src/utils.py") == b"utils code"
    assert vault.read("project/README.md") == b"readme"


def test_copy_empty_path(temp_db):
    """Test that copying with empty source raises ValueError."""
    vault = Vault(temp_db, "cp_empty_user")

    vault.write("file.txt", b"Content")

    try:
        vault.copy("", "dst.txt")
        assert False, "Should raise ValueError for empty source"
    except ValueError:
        pass


def test_copy_binary_data(temp_db):
    """Test copying binary files."""
    vault = Vault(temp_db, "cp_binary_user")

    binary = b"\x00\x01\xff\xfe\x42"
    vault.write("bin.dat", binary)
    vault.copy("bin.dat", "bin_copy.dat")

    assert vault.read("bin_copy.dat") == binary


def test_copy_during_commit(temp_db):
    """Test that copy works during a commit."""
    vault = Vault(temp_db, "cp_commit_user")

    vault.write("file.txt", b"Content")

    vault.begin_commit()
    vault.copy("file.txt", "copy.txt")
    vault.end_commit("Copy file")

    assert vault.read("copy.txt") == b"Content"

    # Should be revertible
    commits = vault.commit_log()
    vault.revert_commit(commits[0].commit_id)
    assert "copy.txt" not in vault.list(), "Copy should be reverted"


def test_copy_isolated_between_users(temp_db):
    """Test that copy only sees files from the same user."""
    vault1 = Vault(temp_db, "user1")
    vault2 = Vault(temp_db, "user2")

    vault1.write("file.txt", b"User1 content")

    try:
        vault2.copy("file.txt", "stolen.txt")
        assert False, "Should raise FileNotFoundError (file belongs to user1)"
    except FileNotFoundError:
        pass


# ========== MOVE TESTS ==========


def test_move_file(temp_db):
    """Test moving (renaming) a file."""
    vault = Vault(temp_db, "mv_user")

    vault.write("old/path.txt", b"Hello, World!")

    vault.move("old/path.txt", "new/path.txt")

    # Source should be gone, destination should exist
    assert vault.read("new/path.txt") == b"Hello, World!", "Destination should have content"

    try:
        vault.read("old/path.txt")
        assert False, "Source should not exist after move"
    except FileNotFoundError:
        pass

    files = vault.list()
    assert "old/path.txt" not in files, "Source should not be in list"
    assert "new/path.txt" in files, "Destination should be in list"


def test_move_file_overwrites_destination(temp_db):
    """Test that moving overwrites existing destination file."""
    vault = Vault(temp_db, "mv_overwrite_user")

    vault.write("src.txt", b"New content")
    vault.write("dst.txt", b"Old content")

    vault.move("src.txt", "dst.txt")

    assert vault.read("dst.txt") == b"New content", "Destination should be overwritten"
    assert "src.txt" not in vault.list(), "Source should be gone"


def test_move_nonexistent_source(temp_db):
    """Test that moving a nonexistent file raises FileNotFoundError."""
    vault = Vault(temp_db, "mv_noent_user")

    try:
        vault.move("nonexistent.txt", "dst.txt")
        assert False, "Should raise FileNotFoundError"
    except FileNotFoundError:
        pass


def test_move_directory(temp_db):
    """Test moving a directory."""
    vault = Vault(temp_db, "mv_dir_user")

    vault.write("old_dir/file1.txt", b"File 1")
    vault.write("old_dir/file2.txt", b"File 2")
    vault.write("old_dir/sub/file3.txt", b"File 3")

    vault.move("old_dir", "new_dir")

    # New paths should exist
    assert vault.read("new_dir/file1.txt") == b"File 1"
    assert vault.read("new_dir/file2.txt") == b"File 2"
    assert vault.read("new_dir/sub/file3.txt") == b"File 3"

    # Old paths should be gone
    files = vault.list()
    assert not any(f.startswith("old_dir/") for f in files), "Old directory files should be gone"


def test_move_empty_path(temp_db):
    """Test that moving with empty source raises ValueError."""
    vault = Vault(temp_db, "mv_empty_user")

    vault.write("file.txt", b"Content")

    try:
        vault.move("", "dst.txt")
        assert False, "Should raise ValueError for empty source"
    except ValueError:
        pass


def test_move_during_commit(temp_db):
    """Test that move works during a commit."""
    vault = Vault(temp_db, "mv_commit_user")

    vault.write("old.txt", b"Content")

    vault.begin_commit()
    vault.move("old.txt", "new.txt")
    vault.end_commit("Move file")

    assert vault.read("new.txt") == b"Content"
    assert "old.txt" not in vault.list()

    # Revert should undo the move
    commits = vault.commit_log()
    vault.revert_commit(commits[0].commit_id)
    assert vault.read("old.txt") == b"Content", "Original should be restored"
    assert "new.txt" not in vault.list(), "Moved file should be reverted"


def test_move_isolated_between_users(temp_db):
    """Test that move only sees files from the same user."""
    vault1 = Vault(temp_db, "user1")
    vault2 = Vault(temp_db, "user2")

    vault1.write("file.txt", b"User1 content")

    try:
        vault2.move("file.txt", "stolen.txt")
        assert False, "Should raise FileNotFoundError (file belongs to user1)"
    except FileNotFoundError:
        pass

    # Original should still exist for user1
    assert vault1.read("file.txt") == b"User1 content"


def test_move_binary_data(temp_db):
    """Test moving binary files."""
    vault = Vault(temp_db, "mv_binary_user")

    binary = b"\x00\x01\xff\xfe\x42"
    vault.write("bin.dat", binary)
    vault.move("bin.dat", "moved.dat")

    assert vault.read("moved.dat") == binary
    assert "bin.dat" not in vault.list()


# ========== VACUUM TESTS ==========


def test_vacuum(temp_db):
    """Test that vacuum runs successfully and returns bytes reclaimed."""
    vault = Vault(temp_db, "vacuum_user")

    # Write and delete several files to create reclaimable space
    for i in range(50):
        vault.write(f"tmp/file{i}.txt", b"X" * 1000)
    for i in range(50):
        vault.delete(f"tmp/file{i}.txt")

    reclaimed = vault.vacuum()
    assert isinstance(reclaimed, int)
    assert reclaimed >= 0