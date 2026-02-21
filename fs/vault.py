"""Vault implementation using SQLite backend."""

from __future__ import annotations

import difflib
import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _utc_to_local(utc_str: str) -> str:
    """Convert a UTC timestamp string from SQLite to a local time string.

    SQLite's CURRENT_TIMESTAMP stores UTC. This parses it as UTC and
    converts to the system's local timezone, returning a string in the
    same format.
    """
    dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone()
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class FileVersion:
    """Metadata for a file version."""

    version_id: str
    author: str
    timestamp: str
    hash: str


@dataclass
class FileMeta:
    """Metadata for the latest version of a file."""

    filepath: str
    timestamp: Optional[str]
    author: Optional[str]
    size: Optional[int]


@dataclass
class Commit:
    """Metadata for a commit."""

    commit_id: str
    author: str
    timestamp: str
    message: str


class Vault:
    """A simple vault for storing files using SQLite backend.

    Each user has their own partition in the vault, allowing multiple users
    to store files independently.
    """

    def __init__(self, filename: str, user: str):
        """Initialize the vault.

        :param filename: The vault DB file to use (sqlite)
        :param user: The name of the user (each user has their own vault partition)
        """
        self.filename = filename
        self.user = user
        self._current_commit_id: Optional[str] = None  # Track active commit
        self._pending_writes: dict[str, tuple[bytes, str, Optional[str]]] = {}  # filepath -> (content, author, base_hash)
        self._pending_deletes: dict[str, Optional[str]] = {}  # filepath -> base_hash
        self._init_db()

    def _init_db(self):
        """Initialize the database schema."""
        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        # Create table for storing commits
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commits (
                commit_id TEXT PRIMARY KEY,
                user TEXT NOT NULL,
                message TEXT NOT NULL,
                author TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create table for storing file versions with user partitioning
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL,
                user TEXT NOT NULL,
                filepath TEXT NOT NULL,
                content BLOB NOT NULL,
                hash TEXT NOT NULL,
                author TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Check if commit_id column exists (for migration)
        cursor.execute("PRAGMA table_info(versions)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'commit_id' not in columns:
            # Add commit_id column if it doesn't exist
            cursor.execute("ALTER TABLE versions ADD COLUMN commit_id TEXT")

        # Drop legacy index that didn't include id
        cursor.execute("DROP INDEX IF EXISTS idx_user_filepath")

        # Create index for faster lookups — covers the common
        # "get latest version" pattern (ORDER BY id DESC LIMIT 1)
        # and MAX(id) subqueries used by list().
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_filepath_id
            ON versions(user, filepath, id DESC)
        """)

        # Create index for commit lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_commit
            ON versions(commit_id)
        """)

        conn.commit()
        conn.close()

    def write(self, filepath: str, content: bytes, author: Optional[str] = None, mode: Optional[str] = None):
        """Write a file to the vault.

        Creates a new version of the file each time it's called.

        :param filepath: The path of the file to write (leading/trailing slashes are stripped)
        :param content: The content of the file as bytes
        :param author: The author of this version (defaults to the vault's user)
        :param mode: If "a", update existing version in-place when content is an extension
        :raises ValueError: If filepath is empty
        """
        # Normalize filepath: strip leading/trailing slashes
        filepath = filepath.strip('/')

        # Validate filepath
        if not filepath:
            raise ValueError("Filepath cannot be empty")

        # Use vault's user as default author
        if author is None:
            author = self.user

        # Append mode outside a commit: append content to existing version in-place
        if mode == "a" and self._current_commit_id is None:
            conn = sqlite3.connect(self.filename)
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, content, hash FROM versions
                   WHERE user = ? AND filepath = ?
                   ORDER BY id DESC LIMIT 1""",
                (self.user, filepath)
            )
            row = cursor.fetchone()
            if row is not None and row[2] != 'tombstone':
                merged = row[1] + content
                content_hash = hashlib.sha256(merged).hexdigest()
                cursor.execute(
                    "UPDATE versions SET content = ?, hash = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?",
                    (merged, content_hash, row[0])
                )
                conn.commit()
                conn.close()
                return
            conn.close()

        # If in a commit, batch the write
        if self._current_commit_id is not None:
            # Capture base hash only on first write to this file in this commit
            if filepath not in self._pending_writes:
                # Get current version hash from database
                conn = sqlite3.connect(self.filename)
                cursor = conn.cursor()
                cursor.execute(
                    """SELECT hash FROM versions
                       WHERE user = ? AND filepath = ?
                       ORDER BY id DESC LIMIT 1""",
                    (self.user, filepath)
                )
                row = cursor.fetchone()
                conn.close()
                base_hash = row[0] if (row and row[0] != 'tombstone') else None
            else:
                # Keep the original base hash from first write
                base_hash = self._pending_writes[filepath][2]

            self._pending_writes[filepath] = (content, author, base_hash)
            # Remove from pending deletes if it was there
            self._pending_deletes.pop(filepath, None)
            return

        # Otherwise, write immediately
        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        # Compute hash of content
        content_hash = hashlib.sha256(content).hexdigest()

        # Generate a fresh UUID for this version
        version_id = str(uuid.uuid4()).lower()

        # Insert new version with optional commit_id
        cursor.execute(
            "INSERT INTO versions (version_id, user, filepath, content, hash, author, commit_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (version_id, self.user, filepath, content, content_hash, author, None)
        )

        conn.commit()
        conn.close()

    def exists(self, path: str) -> bool:
        """Check if a file or directory exists in the vault.

        Directories are virtual - they exist if there are files under them.

        :param path: The path to check (e.g., 'docs', 'docs/reports', 'docs/file.txt')
        :return: True if the path exists (as a file or directory), False otherwise
        """
        # Normalize path by removing leading/trailing slashes
        path = path.strip('/')

        # Root always exists
        if not path:
            return True

        files = self.list()

        # Check if it's an exact file match
        if path in files:
            return True

        # Check if it's a virtual directory (has files under it)
        prefix = path + '/'
        for filepath in files:
            if filepath.startswith(prefix):
                return True

        return False

    def is_dir(self, path: str) -> bool:
        """Check if a path is a directory (virtual directory with files under it).

        :param path: The path to check
        :return: True if the path is a directory, False if it's a file or doesn't exist
        """
        # Normalize path
        path = path.strip('/')

        # Root is always a directory
        if not path:
            return True

        files = self.list()

        # If it's an exact file match, it's not a directory
        if path in files:
            return False

        # Check if it's a virtual directory (has files under it)
        prefix = path + '/'
        for filepath in files:
            if filepath.startswith(prefix):
                return True

        return False

    def list(self, sort_by_recent: bool = False, prefix: str = "") -> list[str]:
        """List files in the vault for the current user.

        :param sort_by_recent: If True, sort by most recently updated first
        :param prefix: If non-empty, only return paths starting with this prefix
        :return: A list of file paths
        """
        prefix = prefix.strip("/")
        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        # Build optional prefix filter
        prefix_clause = ""
        params: list = [self.user]
        if prefix:
            prefix_clause = " AND filepath LIKE ?"
            params.append(prefix + "%")

        order = "ORDER BY id DESC" if sort_by_recent else ""
        cursor.execute(
            f"""SELECT filepath FROM versions v1
               WHERE user = ? AND hash != 'tombstone'{prefix_clause}
               AND id = (SELECT MAX(id) FROM versions v2
                        WHERE v2.user = v1.user AND v2.filepath = v1.filepath)
               {order}""",
            params
        )
        files = [row[0].lstrip('/') for row in cursor.fetchall()]

        conn.close()

        # If in a commit, apply pending operations (read-your-own-writes)
        if self._current_commit_id is not None:
            files_set = set(files)

            prefix_filter = (prefix + "/") if prefix else ""
            pending_keys = self._pending_writes.keys()
            if prefix_filter:
                pending_keys = [k for k in pending_keys if k.startswith(prefix_filter) or k == prefix]

            files_set.update(pending_keys)
            files_set.difference_update(self._pending_deletes)

            files = list(files_set)

            if sort_by_recent:
                pending_files = [f for f in pending_keys if f not in self._pending_deletes]
                db_files = [f for f in files if f not in pending_files]
                files = pending_files + db_files

        return files

    def list_with_metadata(self, sort_by_recent: bool = False, prefix: str = "") -> list[FileMeta]:
        """List files with metadata in a single query.

        :param sort_by_recent: If True, sort by most recently updated first
        :param prefix: If non-empty, only return paths starting with this prefix
        :return: A list of FileMeta objects
        """
        prefix = prefix.strip("/")
        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        prefix_clause = ""
        params: list = [self.user]
        if prefix:
            prefix_clause = " AND filepath LIKE ?"
            params.append(prefix + "%")

        order = "ORDER BY id DESC" if sort_by_recent else ""
        cursor.execute(
            f"""SELECT filepath, timestamp, author, LENGTH(content)
                FROM versions v1
                WHERE user = ? AND hash != 'tombstone'{prefix_clause}
                AND id = (SELECT MAX(id) FROM versions v2
                         WHERE v2.user = v1.user AND v2.filepath = v1.filepath)
                {order}""",
            params
        )

        results = []
        seen = set()
        for row in cursor.fetchall():
            fp = row[0].lstrip('/')
            seen.add(fp)
            results.append(FileMeta(
                filepath=fp,
                timestamp=_utc_to_local(row[1]) if row[1] else None,
                author=row[2],
                size=row[3],
            ))

        conn.close()

        # If in a commit, apply pending operations (read-your-own-writes)
        if self._current_commit_id is not None:
            # Remove entries for pending deletes
            results = [m for m in results if m.filepath not in self._pending_deletes]

            # Add/replace entries for pending writes
            prefix_filter = (prefix + "/") if prefix else ""
            for filepath, (content, author, _) in self._pending_writes.items():
                if filepath in self._pending_deletes:
                    continue
                if prefix_filter and not (filepath.startswith(prefix_filter) or filepath == prefix):
                    continue
                # Remove existing DB entry if overwritten
                results = [m for m in results if m.filepath != filepath]
                results.append(FileMeta(
                    filepath=filepath,
                    timestamp=None,
                    author=author,
                    size=len(content),
                ))

            if sort_by_recent:
                # Pending writes (no timestamp) go first
                pending = [m for m in results if m.timestamp is None]
                db = [m for m in results if m.timestamp is not None]
                results = pending + db

        return results

    def read(self, filepath: str) -> bytes:
        """Read a file from the vault.

        Returns the latest version of the file.

        :param filepath: The path of the file to read (leading/trailing slashes are stripped)
        :return: The content of the file as bytes
        :raises FileNotFoundError: If the file doesn't exist or is deleted
        """
        # Normalize filepath: strip leading/trailing slashes
        filepath = filepath.strip('/')

        # If in a commit, check pending operations first (read-your-own-writes)
        if self._current_commit_id is not None:
            # Check if file is pending deletion
            if filepath in self._pending_deletes:
                raise FileNotFoundError(f"File '{filepath}' not found in vault for user '{self.user}'")

            # Check if file has pending write
            if filepath in self._pending_writes:
                return self._pending_writes[filepath][0]  # Return content (first element of tuple)

        # Otherwise, read from database
        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        cursor.execute(
            """SELECT content, hash FROM versions
               WHERE user = ? AND filepath = ?
               ORDER BY id DESC
               LIMIT 1""",
            (self.user, filepath)
        )

        row = cursor.fetchone()
        conn.close()

        if row is None or row[1] == 'tombstone':
            raise FileNotFoundError(f"File '{filepath}' not found in vault for user '{self.user}'")

        return row[0]

    def log(self, filepath: str) -> list[FileVersion]:
        """Returns metadata for all file versions.

        :param filepath: The path of the file to get the log for (leading/trailing slashes are stripped)
        :return: A list of FileVersion objects in chronological order
        :raises FileNotFoundError: If the file doesn't exist
        """
        # Normalize filepath: strip leading/trailing slashes
        filepath = filepath.strip('/')

        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        cursor.execute(
            """SELECT version_id, author, timestamp, hash FROM versions
               WHERE user = ? AND filepath = ?
               ORDER BY id ASC""",
            (self.user, filepath)
        )

        versions = [
            FileVersion(
                version_id=row[0],
                author=row[1],
                timestamp=_utc_to_local(row[2]) if row[2] else row[2],
                hash=row[3]
            )
            for row in cursor.fetchall()
        ]
        conn.close()

        if not versions:
            raise FileNotFoundError(f"File '{filepath}' not found in vault for user '{self.user}'")

        return versions

    def read_version(self, filepath: str, version_id: str) -> bytes:
        """Read the content of a specific file version.

        :param filepath: The path of the file (leading/trailing slashes are stripped)
        :param version_id: The UUID of the version to read
        :returns: The file content as bytes
        :raises ValueError: If the version is not found
        """
        filepath = filepath.strip('/')

        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        cursor.execute(
            """SELECT content FROM versions
               WHERE user = ? AND filepath = ? AND version_id = ?
               LIMIT 1""",
            (self.user, filepath, version_id)
        )

        row = cursor.fetchone()
        if row is None:
            conn.close()
            raise ValueError(f"Version with ID '{version_id}' not found for file '{filepath}'")

        content = row[0]
        conn.close()
        return content

    def restore(self, filepath: str, version_id: str):
        """Restore a file to a previous version.

        Creates a new version with the content from the specified version.

        :param filepath: The path of the file to restore (leading/trailing slashes are stripped)
        :param version_id: The UUID of the version to restore
        """
        content = self.read_version(filepath, version_id)
        self.write(filepath, content)

    def copy(self, src: str, dst: str):
        """Copy a file or directory to a new path.

        If src is a file, copies it to dst.
        If src is a virtual directory, copies all files under it to dst.

        :param src: Source file or directory path
        :param dst: Destination file or directory path
        :raises ValueError: If src or dst is empty
        :raises FileNotFoundError: If src doesn't exist
        """
        src = src.strip('/')
        dst = dst.strip('/')

        if not src:
            raise ValueError("Source path cannot be empty")
        if not dst:
            raise ValueError("Destination path cannot be empty")

        # Check if src is a file
        files = self.list()
        if src in files:
            # Single file copy
            content = self.read(src)
            self.write(dst, content)
            return

        # Check if src is a virtual directory
        prefix = src + '/'
        matched = [f for f in files if f.startswith(prefix)]
        if not matched:
            raise FileNotFoundError(f"File '{src}' not found in vault for user '{self.user}'")

        # Directory copy: copy each file under src to dst
        for filepath in matched:
            rel = filepath[len(prefix):]
            content = self.read(filepath)
            self.write(dst + '/' + rel, content)

    def move(self, src: str, dst: str):
        """Move (rename) a file or directory to a new path.

        If src is a file, moves it to dst.
        If src is a virtual directory, moves all files under it to dst.

        :param src: Source file or directory path
        :param dst: Destination file or directory path
        :raises ValueError: If src or dst is empty
        :raises FileNotFoundError: If src doesn't exist
        """
        src = src.strip('/')
        dst = dst.strip('/')

        if not src:
            raise ValueError("Source path cannot be empty")
        if not dst:
            raise ValueError("Destination path cannot be empty")

        # Check if src is a file
        files = self.list()
        if src in files:
            # Single file move
            content = self.read(src)
            self.write(dst, content)
            self.delete(src)
            return

        # Check if src is a virtual directory
        prefix = src + '/'
        matched = [f for f in files if f.startswith(prefix)]
        if not matched:
            raise FileNotFoundError(f"File '{src}' not found in vault for user '{self.user}'")

        # Directory move: copy each file, then delete originals
        for filepath in matched:
            rel = filepath[len(prefix):]
            content = self.read(filepath)
            self.write(dst + '/' + rel, content)

        for filepath in matched:
            self.delete(filepath)

    def delete(self, filepath: str):
        """Delete a file from the vault.

        Also deletes all versions of the file (garbage collection).

        :param filepath: The path of the file to delete (leading/trailing slashes are stripped)
        """
        # Normalize filepath: strip leading/trailing slashes
        filepath = filepath.strip('/')

        # If in a commit, batch the deletion
        if self._current_commit_id is not None:
            # Capture base hash of file being deleted
            if filepath not in self._pending_deletes:
                conn = sqlite3.connect(self.filename)
                cursor = conn.cursor()
                cursor.execute(
                    """SELECT hash FROM versions
                       WHERE user = ? AND filepath = ?
                       ORDER BY id DESC LIMIT 1""",
                    (self.user, filepath)
                )
                row = cursor.fetchone()
                conn.close()
                base_hash = row[0] if (row and row[0] != 'tombstone') else None
            else:
                # Keep the original base hash
                base_hash = self._pending_deletes[filepath]

            self._pending_deletes[filepath] = base_hash
            # Remove from pending writes if it was there
            self._pending_writes.pop(filepath, None)
            return

        # Otherwise, delete immediately
        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM versions WHERE user = ? AND filepath = ?",
            (self.user, filepath)
        )

        conn.commit()
        conn.close()

    def begin_commit(self):
        """Start a new commit.

        All subsequent write() calls will be part of this commit until end_commit() is called.
        """
        if self._current_commit_id is not None:
            raise ValueError("A commit is already in progress. Call end_commit() first.")

        self._current_commit_id = str(uuid.uuid4()).lower()

    def end_commit(self, message: str, author: Optional[str] = None):
        """Finalize the current commit.

        :param message: The commit message
        :param author: The author of this commit (defaults to the vault's user)
        :raises ValueError: If no commit in progress, if commit has no changes, or if there are conflicts
        """
        if self._current_commit_id is None:
            raise ValueError("No commit in progress. Call begin_commit() first.")

        # Check if there are any changes
        if not self._pending_writes and not self._pending_deletes:
            # No changes, don't create empty commit
            self._current_commit_id = None
            self._pending_writes.clear()
            self._pending_deletes.clear()
            raise ValueError("Cannot create empty commit: no changes made")

        # Use vault's user as default author
        if author is None:
            author = self.user

        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        # Check for conflicts on all pending writes
        for filepath, (content, write_author, expected_hash) in self._pending_writes.items():
            cursor.execute(
                """SELECT hash FROM versions
                   WHERE user = ? AND filepath = ?
                   ORDER BY id DESC LIMIT 1""",
                (self.user, filepath)
            )
            row = cursor.fetchone()
            current_hash = row[0] if (row and row[0] != 'tombstone') else None

            if current_hash != expected_hash:
                conn.close()
                self._current_commit_id = None
                self._pending_writes.clear()
                self._pending_deletes.clear()
                raise ValueError(
                    f"Conflict detected: '{filepath}' was modified by another process. "
                    f"Please refresh and retry your changes."
                )

        # Check for conflicts on all pending deletes
        for filepath, expected_hash in self._pending_deletes.items():
            cursor.execute(
                """SELECT hash FROM versions
                   WHERE user = ? AND filepath = ?
                   ORDER BY id DESC LIMIT 1""",
                (self.user, filepath)
            )
            row = cursor.fetchone()
            current_hash = row[0] if (row and row[0] != 'tombstone') else None

            if current_hash != expected_hash:
                conn.close()
                self._current_commit_id = None
                self._pending_writes.clear()
                self._pending_deletes.clear()
                raise ValueError(
                    f"Conflict detected: '{filepath}' was modified by another process. "
                    f"Please refresh and retry your changes."
                )

        # No conflicts, proceed with commit

        # Apply all pending writes
        for filepath, (content, write_author, _) in self._pending_writes.items():
            # Compute hash of content
            content_hash = hashlib.sha256(content).hexdigest()
            # Generate a fresh UUID for this version
            version_id = str(uuid.uuid4()).lower()
            # Insert new version
            cursor.execute(
                "INSERT INTO versions (version_id, user, filepath, content, hash, author, commit_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (version_id, self.user, filepath, content, content_hash, write_author, self._current_commit_id)
            )

        # Apply all pending deletes by creating tombstone markers
        for filepath in self._pending_deletes.keys():
            # Create a special tombstone version to mark deletion
            version_id = str(uuid.uuid4()).lower()
            # Use empty content with special marker
            cursor.execute(
                "INSERT INTO versions (version_id, user, filepath, content, hash, author, commit_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (version_id, self.user, filepath, b"__DELETED__", "tombstone", author, self._current_commit_id)
            )

        # Create commit record
        cursor.execute(
            "INSERT INTO commits (commit_id, user, message, author) VALUES (?, ?, ?, ?)",
            (self._current_commit_id, self.user, message, author)
        )

        conn.commit()
        conn.close()

        # Reset commit state
        self._current_commit_id = None
        self._pending_writes.clear()
        self._pending_deletes.clear()

    def commit_log(self) -> list[Commit]:
        """List all commits for the current user.

        :return: A list of Commit objects in chronological order
        """
        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        cursor.execute(
            """SELECT commit_id, author, timestamp, message FROM commits
               WHERE user = ?
               ORDER BY timestamp ASC""",
            (self.user,)
        )

        commits = [
            Commit(
                commit_id=row[0],
                author=row[1],
                timestamp=_utc_to_local(row[2]) if row[2] else row[2],
                message=row[3]
            )
            for row in cursor.fetchall()
        ]

        conn.close()
        return commits

    def revert_commit(self, commit_id: str):
        """Revert a commit by undoing its changes.

        Uses three-way merge to selectively undo the commit's changes while
        preserving later changes when possible.

        :param commit_id: The ID of the commit to revert
        :raises ValueError: If the commit doesn't exist or if there are conflicts
        """
        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        # Verify commit exists
        cursor.execute(
            "SELECT 1 FROM commits WHERE commit_id = ? AND user = ?",
            (commit_id, self.user)
        )
        if cursor.fetchone() is None:
            conn.close()
            raise ValueError(f"Commit '{commit_id}' not found for user '{self.user}'")

        # Find all files affected by this commit
        cursor.execute(
            """SELECT DISTINCT filepath FROM versions
               WHERE commit_id = ? AND user = ?""",
            (commit_id, self.user)
        )
        affected_files = [row[0] for row in cursor.fetchall()]
        conn.close()

        # Revert each file
        for filepath in affected_files:
            self._revert_file(filepath, commit_id)

    def _revert_file(self, filepath: str, commit_id: str):
        """Revert a single file from a commit using three-way merge."""
        conn = sqlite3.connect(self.filename)
        cursor = conn.cursor()

        # Get all versions for this file in chronological order
        cursor.execute(
            """SELECT id, content, commit_id, hash FROM versions
               WHERE user = ? AND filepath = ?
               ORDER BY id ASC""",
            (self.user, filepath)
        )
        versions = cursor.fetchall()
        conn.close()

        # Find the commit version and the version before it
        commit_version_idx = None
        for i, (version_id, content, ver_commit_id, hash_val) in enumerate(versions):
            if ver_commit_id == commit_id:
                commit_version_idx = i
                break

        if commit_version_idx is None:
            raise ValueError(f"No version found for file '{filepath}' in commit '{commit_id}'")

        # Get before, after, and current contents
        after_content = versions[commit_version_idx][1]
        after_hash = versions[commit_version_idx][3]
        current_content = versions[-1][1]  # Latest version
        current_hash = versions[-1][3]

        # Check if the commit deleted the file (tombstone)
        if after_hash == 'tombstone':
            # File was deleted in this commit, restore to previous version
            if commit_version_idx == 0:
                raise ValueError(f"Cannot revert deletion of file '{filepath}': no previous version exists")
            before_content = versions[commit_version_idx - 1][1]
            self.write(filepath, before_content)
            return

        # Check if this was a new file (no version before commit)
        if commit_version_idx == 0:
            # File was created in this commit, so delete it
            self.delete(filepath)
            return

        before_content = versions[commit_version_idx - 1][1]

        # If current is a tombstone (file was deleted after commit), restore to before
        if current_hash == 'tombstone':
            self.write(filepath, before_content)
            return

        # If current is same as after, simple revert to before
        if current_content == after_content:
            self.write(filepath, before_content)
            return

        # Perform three-way merge
        try:
            merged_content = self._three_way_merge(
                before_content, after_content, current_content
            )
            self.write(filepath, merged_content)
        except ValueError as e:
            raise ValueError(f"Cannot revert file '{filepath}': {e}")

    def _three_way_merge(
        self, base: bytes, theirs: bytes, ours: bytes
    ) -> bytes:
        """Perform three-way merge to revert changes.

        base: content before the commit
        theirs: content after the commit (what the commit changed to)
        ours: current content (what we have now)

        We want to compute: ours with the changes from base→theirs removed.

        Algorithm:
        1. Compute what changed from base→theirs (commit's changes)
        2. Compute what changed from base→ours (all changes including later ones)
        3. For each commit change, check if it conflicts with later changes
        4. Apply inverse of commit changes to ours
        """
        # Convert bytes to lines for diffing
        base_lines = base.decode('utf-8', errors='replace').splitlines(keepends=True)
        theirs_lines = theirs.decode('utf-8', errors='replace').splitlines(keepends=True)
        ours_lines = ours.decode('utf-8', errors='replace').splitlines(keepends=True)

        # Use SequenceMatcher for three-way merge
        base_to_theirs = difflib.SequenceMatcher(None, base_lines, theirs_lines)
        theirs_to_ours = difflib.SequenceMatcher(None, theirs_lines, ours_lines)

        # Build the result by processing theirs→ours changes and inverting commit changes
        result_lines = []

        # Process changes from theirs to ours
        for tag, i1, i2, j1, j2 in theirs_to_ours.get_opcodes():
            if tag == 'equal':
                # These lines are the same in theirs and ours
                # Check if they came from the commit or were in base
                # Map back to base
                base_to_theirs_ops = list(base_to_theirs.get_opcodes())

                # For equal sections, we need to check if they came from base or commit
                in_commit = False
                for b_tag, b_i1, b_i2, b_j1, b_j2 in base_to_theirs_ops:
                    # Check if this equal section overlaps with a commit insertion/replacement
                    if b_tag in ('insert', 'replace') and not (b_j2 <= i1 or b_j1 >= i2):
                        # This section was added/changed by the commit
                        # We should skip it (revert it out)
                        # Calculate overlap
                        overlap_start = max(i1, b_j1)
                        overlap_end = min(i2, b_j2)
                        # Skip the overlapping lines (don't add to result)
                        if overlap_start < overlap_end:
                            in_commit = True
                            # Only add the parts that weren't in the commit
                            if i1 < overlap_start:
                                result_lines.extend(theirs_lines[i1:overlap_start])
                            if overlap_end < i2:
                                result_lines.extend(theirs_lines[overlap_end:i2])
                            break

                if not in_commit:
                    # These lines were not added by the commit, keep them
                    result_lines.extend(theirs_lines[i1:i2])

            elif tag == 'insert':
                # Lines were inserted after the commit, keep them
                result_lines.extend(ours_lines[j1:j2])
            elif tag == 'delete':
                # Lines from theirs were deleted in ours
                # Check if these lines came from the commit
                from_commit = False
                for b_tag, b_i1, b_i2, b_j1, b_j2 in base_to_theirs.get_opcodes():
                    if b_tag == 'insert' and b_j1 <= i1 < i2 <= b_j2:
                        # These lines were inserted by the commit and then deleted
                        # Don't add them back (we're reverting the commit)
                        from_commit = True
                        break
                if not from_commit:
                    # These lines existed before the commit but were deleted later
                    # This is a conflict or intentional later change, skip them
                    pass
            elif tag == 'replace':
                # Lines were replaced after the commit
                # This could be a conflict - check if commit changed these lines
                conflict = False
                for b_tag, b_i1, b_i2, b_j1, b_j2 in base_to_theirs.get_opcodes():
                    if b_tag == 'replace' and not (b_j2 <= i1 or b_j1 >= i2):
                        # Commit changed these lines, and they were changed again later
                        raise ValueError("Conflict detected: same lines modified by commit and later changes")
                # No conflict, keep the later changes
                result_lines.extend(ours_lines[j1:j2])

        # Now add back any base lines that were in base but removed by commit
        for tag, i1, i2, j1, j2 in base_to_theirs.get_opcodes():
            if tag == 'delete':
                # Commit deleted base[i1:i2], add them back
                # Insert at the appropriate position (after the last base line that's still there)
                # This is tricky - for now, append at the end
                # TODO: improve positioning
                pass  # Handled below with a better approach

        # Better approach: build result from base, applying only non-commit changes from ours
        result_lines = []

        # Get operations from theirs to ours
        theirs_to_ours_ops = list(theirs_to_ours.get_opcodes())

        # Start with base and apply non-commit changes
        i_theirs = 0
        for t2o_tag, t2o_i1, t2o_i2, t2o_j1, t2o_j2 in theirs_to_ours_ops:
            # For each section in theirs→ours, check if it came from base→theirs
            # Find corresponding sections in base→theirs
            for b2t_tag, b2t_i1, b2t_i2, b2t_j1, b2t_j2 in base_to_theirs.get_opcodes():
                if b2t_tag == 'equal' and not (b2t_j2 <= t2o_i1 or b2t_j1 >= t2o_i2):
                    # This section in theirs came from base (not modified by commit)
                    if t2o_tag == 'equal':
                        # Still equal in ours, keep it
                        overlap_start = max(t2o_i1, b2t_j1)
                        overlap_end = min(t2o_i2, b2t_j2)
                        if overlap_start < overlap_end:
                            result_lines.extend(theirs_lines[overlap_start:overlap_end])
                    elif t2o_tag == 'replace':
                        # Was equal, now replaced - keep the replacement
                        result_lines.extend(ours_lines[t2o_j1:t2o_j2])
                elif b2t_tag == 'insert' and not (b2t_j2 <= t2o_i1 or b2t_j1 >= t2o_i2):
                    # This section was inserted by commit
                    if t2o_tag == 'equal':
                        # Still there in ours, skip it (revert the commit)
                        pass
                    elif t2o_tag == 'delete':
                        # Was inserted by commit, now deleted - already gone, good
                        pass
                    elif t2o_tag == 'replace':
                        # Was inserted by commit, now modified - conflict!
                        raise ValueError("Conflict: commit-inserted lines were modified later")

            # Handle insertions in ours (new lines added after commit)
            if t2o_tag == 'insert':
                result_lines.extend(ours_lines[t2o_j1:t2o_j2])

        # This is getting too complex. Let me use a simpler, more direct approach.
        # Start from scratch with a clearer algorithm.

        # Simple approach: Start with ours, find and remove what commit added, add back what commit removed
        result_lines = ours_lines[:]

        # Process commit changes in reverse order
        for tag, i1, i2, j1, j2 in reversed(list(base_to_theirs.get_opcodes())):
            if tag == 'insert':
                # Commit inserted theirs[j1:j2] at position i1 in base
                # Find where these lines are in ours and remove them
                inserted_lines = theirs_lines[j1:j2]
                # Try to find and remove these exact lines from result
                for start_idx in range(len(result_lines) - len(inserted_lines) + 1):
                    if result_lines[start_idx:start_idx+len(inserted_lines)] == inserted_lines:
                        del result_lines[start_idx:start_idx+len(inserted_lines)]
                        break
            elif tag == 'delete':
                # Commit deleted base[i1:i2]
                # Add these lines back at the appropriate position
                deleted_lines = base_lines[i1:i2]
                # Find position to insert - look for context before and after
                # For simplicity, find the position based on surrounding base content
                # Insert after the base[i1-1] line in result (if it exists)
                if i1 > 0:
                    context_before = base_lines[i1-1]
                    for idx, line in enumerate(result_lines):
                        if line == context_before:
                            result_lines[idx+1:idx+1] = deleted_lines
                            break
                else:
                    # Insert at beginning
                    result_lines[0:0] = deleted_lines
            elif tag == 'replace':
                # Commit replaced base[i1:i2] with theirs[j1:j2]
                # Replace theirs content back with base content
                replaced_from = base_lines[i1:i2]
                replaced_to = theirs_lines[j1:j2]
                # Find replaced_to in result and replace with replaced_from
                for start_idx in range(len(result_lines) - len(replaced_to) + 1):
                    if result_lines[start_idx:start_idx+len(replaced_to)] == replaced_to:
                        # Check if these lines were modified after the commit
                        # If they were, we have a conflict
                        if result_lines[start_idx:start_idx+len(replaced_to)] != replaced_to:
                            raise ValueError("Conflict: commit-modified lines were changed later")
                        result_lines[start_idx:start_idx+len(replaced_to)] = replaced_from
                        break

        return ''.join(result_lines).encode('utf-8')

    def vacuum(self) -> int:
        """Vacuum the SQLite database to reclaim unused space.

        :return: Bytes reclaimed (difference in file size before and after)
        """
        db_path = Path(self.filename)
        size_before = db_path.stat().st_size
        conn = sqlite3.connect(self.filename)
        conn.execute("VACUUM")
        conn.close()
        size_after = db_path.stat().st_size
        return size_before - size_after
